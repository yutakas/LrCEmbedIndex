import json
import logging
import tempfile
import time
import os
from urllib.parse import unquote

from flask import Blueprint, request, jsonify

from config import (config, get_vision_model_label, get_embed_model_label,
                    save_config, save_last_config_pointer)
from metadata import (load_photo_metadata, save_photo_metadata,
                      get_vision_result, set_vision_result,
                      get_embed_result, set_embed_result,
                      count_metadata_files, collect_metadata_stats)
from vectorstore import init_chromadb, upsert_photo, search_photos, get_chromadb_stats
from vision import describe_image
from embedding import get_embedding
from helpers import exif_to_text, sanitize_chroma_id

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__)


@api.route("/describe", methods=["POST"])
def describe_photo():
    """Vision-only endpoint: describe a single photo, using cached metadata if available."""
    t_start = time.time()
    try:
        image_path = request.headers.get("X-Image-Path", "")

        # Parse EXIF
        exif_raw = request.headers.get("X-Exif-Data", "{}")
        exif_json_str = unquote(exif_raw)
        try:
            exif_data = json.loads(exif_json_str)
        except json.JSONDecodeError:
            exif_data = {}

        jpeg_data = request.get_data()
        if not jpeg_data:
            return jsonify({"status": "error", "message": "No image data received"}), 400

        vision_label = get_vision_model_label()

        # Check cached metadata first
        existing = load_photo_metadata(image_path) if image_path else None
        cached_vision = get_vision_result(existing, vision_label) if existing else None

        if cached_vision and cached_vision.get("full_description"):
            full_description = cached_vision["full_description"]
            vision_description = cached_vision["vision_description"]
            cached_at = cached_vision.get("processed_at", "unknown")
            elapsed = time.time() - t_start
            logger.info(f"POST /describe completed in {elapsed:.1f}s — "
                        f"{image_path} (cached from {cached_at})")
            return jsonify({
                "status": "ok",
                "description": full_description,
                "vision_description": vision_description,
                "vision_model": vision_label,
                "cached": True,
                "cached_at": cached_at,
                "elapsed": round(elapsed, 2),
            })

        # No cache — call vision model
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(jpeg_data)
                tmp_path = tmp.name

            t_vision = time.time()
            logger.info(f"Describe: generating description for {image_path} using {vision_label}")
            vision_description = describe_image(tmp_path)
            logger.info(f"Describe: vision took {time.time() - t_vision:.1f}s")

            # Append EXIF
            exif_text = exif_to_text(exif_data)
            if exif_text:
                full_description = vision_description + "\n\n--- Photo Metadata ---\n" + exif_text
            else:
                full_description = vision_description

            elapsed = time.time() - t_start
            logger.info(f"POST /describe completed in {elapsed:.1f}s — {image_path}")
            return jsonify({
                "status": "ok",
                "description": full_description,
                "vision_description": vision_description,
                "vision_model": vision_label,
                "cached": False,
                "elapsed": round(elapsed, 2),
            })

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /describe failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/index", methods=["POST"])
def index_photo():
    t_start = time.time()
    try:
        image_path = request.headers.get("X-Image-Path", "")
        if not image_path:
            return jsonify({"status": "error", "message": "Missing X-Image-Path header"}), 400

        if not config["index_folder"]:
            return jsonify({"status": "error", "message": "Index folder not configured"}), 500

        # Parse EXIF data from header (percent-encoded JSON)
        exif_raw = request.headers.get("X-Exif-Data", "{}")
        exif_json_str = unquote(exif_raw)
        try:
            exif_data = json.loads(exif_json_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse EXIF JSON: {exif_json_str[:200]}")
            exif_data = {}

        # Save incoming JPEG to a temp file
        jpeg_data = request.get_data()
        if not jpeg_data:
            return jsonify({"status": "error", "message": "No image data received"}), 400

        vision_label = get_vision_model_label()
        embed_label = get_embed_model_label()

        # Load existing metadata (may contain results from other models)
        existing = load_photo_metadata(image_path) or {}

        # --- Vision step: reuse if same vision model already ran ---
        cached_vision = get_vision_result(existing, vision_label)
        if cached_vision and cached_vision.get("full_description"):
            description = cached_vision["full_description"]
            vision_description = cached_vision["vision_description"]
            logger.info(f"Reusing cached vision for {image_path} ({vision_label})")
            need_vision = False
        else:
            need_vision = True

        # --- Embed step: reuse cached embedding if vision+embed pair exists ---
        cached_embed = get_embed_result(existing, vision_label, embed_label)
        need_embed = True
        if (not need_vision
                and cached_embed
                and cached_embed.get("embedding")
                and cached_embed.get("description_used") == description):
            # Embedding already computed for this vision+embed pair.
            # Still upsert to ChromaDB since we don't know which model
            # pair produced the current ChromaDB entry.
            embedding = cached_embed["embedding"]
            need_embed = False
            logger.info(f"Reusing cached embedding for {image_path} "
                        f"({vision_label}/{embed_label})")

        # --- Run vision if needed ---
        tmp_path = None
        try:
            if need_vision:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp.write(jpeg_data)
                    tmp_path = tmp.name

                t_vision = time.time()
                logger.info(f"Generating description for {image_path} using {vision_label}")
                vision_description = describe_image(tmp_path)
                logger.info(f"Vision took {time.time() - t_vision:.1f}s — "
                            f"{vision_description[:100]}...")

                # Append EXIF info to description for richer embedding
                exif_text = exif_to_text(exif_data)
                if exif_text:
                    description = vision_description + "\n\n--- Photo Metadata ---\n" + exif_text
                else:
                    description = vision_description

                # Save vision result (preserves other models' results)
                set_vision_result(existing, vision_label, vision_description,
                                  exif_data, description)

            # --- Generate embedding if needed ---
            if need_embed:
                t_embed = time.time()
                logger.info(f"Generating embedding for {image_path} using {embed_label}")
                embedding = get_embedding(description)
                logger.info(f"Embedding took {time.time() - t_embed:.1f}s")
                if not embedding:
                    return jsonify({"status": "error",
                                    "message": "Failed to generate embedding"}), 500

                # Save embed result nested under the vision result
                set_embed_result(existing, vision_label, embed_label,
                                 embedding, description)

            # Persist metadata
            save_photo_metadata(image_path, existing)

            # Always upsert to ChromaDB — we don't know which model pair
            # produced the current entry, so keep it in sync
            doc_id = sanitize_chroma_id(image_path)
            upsert_photo(doc_id, embedding, description, image_path)

            elapsed = time.time() - t_start
            skipped_parts = []
            if not need_vision:
                skipped_parts.append("vision")
            if not need_embed:
                skipped_parts.append("embed")
            skip_msg = f" (reused: {', '.join(skipped_parts)})" if skipped_parts else ""
            logger.info(f"POST /index completed in {elapsed:.1f}s — "
                        f"{image_path}{skip_msg}")
            return jsonify({
                "status": "ok",
                "description": description,
                "skipped_vision": not need_vision,
                "skipped_embed": not need_embed,
                "elapsed": round(elapsed, 2),
            })

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /index failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/search", methods=["POST"])
def search_photo():
    t_start = time.time()
    try:
        data = request.get_json()
        if not data or "query" not in data:
            return jsonify({"status": "error", "message": "Missing query"}), 400

        query = data["query"]

        # Get embedding for the search query
        t_embed = time.time()
        embedding = get_embedding(query)
        logger.info(f"Search embedding took {time.time() - t_embed:.1f}s")
        if not embedding:
            return jsonify({"status": "error", "message": "Failed to generate query embedding"}), 500

        # Per-request overrides from the search dialog, fall back to config
        max_results = data.get("max_results", config.get("search_max_results", 10))
        relevance = data.get("relevance", config.get("search_relevance", 50))
        matches = search_photos(embedding, n_results=max_results, relevance=relevance)

        elapsed = time.time() - t_start
        logger.info(f"POST /search completed in {elapsed:.1f}s — "
                    f"query='{query}', {len(matches)} results")
        for i, m in enumerate(matches):
            path = os.path.basename(m.get("path", "?"))
            dist = m.get("distance", 0)
            logger.info(f"  #{i+1} dist={dist:.4f}  {path}")
        return jsonify({"status": "ok", "results": matches, "elapsed": round(elapsed, 2)})

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /search failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/settings", methods=["POST"])
def update_settings():
    t_start = time.time()
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        folder_changed = False
        if "index_folder" in data and data["index_folder"] != config["index_folder"]:
            config["index_folder"] = data["index_folder"]
            folder_changed = True

        # Vision settings
        for key in ("vision_mode", "ollama_vision_endpoint", "ollama_vision_model",
                     "openai_vision_api_key", "openai_vision_model",
                     "claude_vision_api_key", "claude_vision_model"):
            if key in data:
                config[key] = data[key]

        # Embedding settings
        for key in ("embed_mode", "ollama_embed_endpoint", "ollama_embed_model",
                     "openai_embed_api_key", "openai_embed_model",
                     "voyage_embed_api_key", "voyage_embed_model"):
            if key in data:
                config[key] = data[key]

        # Search settings
        if "search_max_results" in data:
            config["search_max_results"] = max(1, int(data["search_max_results"]))
        if "search_relevance" in data:
            config["search_relevance"] = max(0, min(100, int(data["search_relevance"])))

        save_config()
        save_last_config_pointer()

        if folder_changed:
            init_chromadb()

        elapsed = time.time() - t_start
        logger.info(f"POST /settings completed in {elapsed:.1f}s — "
                    f"vision={get_vision_model_label()}, "
                    f"embed={get_embed_model_label()}, "
                    f"folder={config['index_folder']}")
        return jsonify({"status": "ok", "config": {
            k: v for k, v in config.items() if "api_key" not in k
        }})

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /settings failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/stats", methods=["GET"])
def get_stats():
    t_start = time.time()
    try:
        # Metadata stats
        meta_count = count_metadata_files()
        meta_stats = collect_metadata_stats()

        # ChromaDB stats
        chroma_stats = get_chromadb_stats()

        # Current config (redact API keys)
        safe_config = {k: v for k, v in config.items() if "api_key" not in k}

        elapsed = time.time() - t_start
        logger.info(f"GET /stats completed in {elapsed:.1f}s")
        return jsonify({
            "status": "ok",
            "metadata": {
                "total_files": meta_count,
                "vision_models": meta_stats.get("vision_models", {}),
                "embed_models": meta_stats.get("embed_models", {}),
                "oldest_entry": meta_stats.get("oldest_entry"),
                "newest_entry": meta_stats.get("newest_entry"),
            },
            "chromadb": chroma_stats,
            "config": safe_config,
            "elapsed": round(elapsed, 2),
        })

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"GET /stats failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
