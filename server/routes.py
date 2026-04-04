import json
import logging
import subprocess
import tempfile
import time
import os
import sys
from urllib.parse import unquote

from flask import Blueprint, request, jsonify, send_file, render_template

from config import (config, get_vision_model_label, get_embed_model_label,
                    save_config, save_last_config_pointer)
from metadata import (load_photo_metadata, save_photo_metadata,
                      get_vision_result, set_vision_result,
                      get_embed_result, set_embed_result,
                      count_metadata_files, collect_metadata_stats,
                      save_thumbnail, has_thumbnail,
                      thumbnail_path_for_image)
from vectorstore import init_chromadb, upsert_photo, search_photos, get_chromadb_stats
from vision import describe_image
from embedding import get_embedding
from helpers import exif_to_text, compute_content_hash, resize_thumbnail_bytes

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__)


@api.route("/", methods=["GET"])
def search_ui():
    """Serve the search web UI."""
    return render_template("search.html")


@api.route("/photo", methods=["GET"])
def photo_detail_ui():
    """Serve the photo detail page."""
    return render_template("photo.html")


@api.route("/metadata", methods=["GET"])
def get_metadata():
    """Return the full metadata JSON for an image path."""
    image_path = request.args.get("path", "")
    if not image_path:
        return jsonify({"status": "error", "message": "Missing 'path' parameter"}), 400

    meta = load_photo_metadata(image_path)
    if not meta:
        return jsonify({"status": "error", "message": "No metadata found"}), 404

    # Strip embedding vectors to keep response small
    safe_meta = json.loads(json.dumps(meta))
    for v_label, v_data in safe_meta.get("vision_results", {}).items():
        for e_label, e_data in v_data.get("embeddings", {}).items():
            if "embedding" in e_data:
                e_data["embedding"] = f"[{len(e_data['embedding'])} dimensions]"

    return jsonify({"status": "ok", "metadata": safe_meta,
                    "has_thumbnail": has_thumbnail(image_path)})


@api.route("/describe", methods=["POST"])
def describe_photo():
    """Vision-only endpoint: return all cached descriptions, or call API if none exist."""
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

        # Check cached metadata — return ALL cached descriptions if any exist
        existing = load_photo_metadata(image_path) if image_path else None
        vision_results = existing.get("vision_results", {}) if existing else {}

        if vision_results:
            # Build list of all cached descriptions
            descriptions = []
            for model_label, v_data in vision_results.items():
                desc = v_data.get("vision_description")
                if desc:
                    descriptions.append({
                        "vision_model": model_label,
                        "vision_description": desc,
                        "full_description": v_data.get("full_description", desc),
                        "processed_at": v_data.get("processed_at", "unknown"),
                    })

            if descriptions:
                elapsed = time.time() - t_start
                logger.info(f"POST /describe completed in {elapsed:.1f}s — "
                            f"{image_path} ({len(descriptions)} cached model(s))")
                return jsonify({
                    "status": "ok",
                    "descriptions": descriptions,
                    "cached": True,
                    "elapsed": round(elapsed, 2),
                })

        # No cache at all — call vision model with current settings
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

            # Cache the result in metadata
            if image_path:
                meta = existing or {}
                set_vision_result(meta, vision_label, vision_description,
                                  exif_data, full_description)
                save_photo_metadata(image_path, meta)

                # Store thumbnail if configured
                thumb_size = config.get("thumbnail_store_size", 512)
                if thumb_size > 0 and not has_thumbnail(image_path):
                    small_thumb = resize_thumbnail_bytes(jpeg_data, max_size=thumb_size)
                    save_thumbnail(image_path, small_thumb)

            elapsed = time.time() - t_start
            logger.info(f"POST /describe completed in {elapsed:.1f}s — {image_path}")
            return jsonify({
                "status": "ok",
                "descriptions": [{
                    "vision_model": vision_label,
                    "vision_description": vision_description,
                    "full_description": full_description,
                    "processed_at": "just now",
                }],
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

            # Store thumbnail if configured
            thumb_size = config.get("thumbnail_store_size", 512)
            if thumb_size > 0 and not has_thumbnail(image_path):
                small_thumb = resize_thumbnail_bytes(jpeg_data, max_size=thumb_size)
                save_thumbnail(image_path, small_thumb)

            # Always upsert to ChromaDB — we don't know which model pair
            # produced the current entry, so keep it in sync
            try:
                doc_id = compute_content_hash(image_path)
            except FileNotFoundError:
                return jsonify({"status": "error",
                                "message": f"Original file not accessible: {image_path}"}), 400
            except PermissionError:
                return jsonify({"status": "error",
                                "message": f"Permission denied reading: {image_path}"}), 403
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

        # Thumbnail settings
        if "thumbnail_store_size" in data:
            config["thumbnail_store_size"] = max(0, int(data["thumbnail_store_size"]))

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
                "thumbnail_files": meta_stats.get("thumbnail_count", 0),
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


@api.route("/thumbnail", methods=["GET"])
def get_thumbnail():
    """Return the stored thumbnail JPEG for an image path."""
    image_path = request.args.get("path", "")
    if not image_path:
        return jsonify({"status": "error", "message": "Missing 'path' parameter"}), 400

    thumb_path = thumbnail_path_for_image(image_path)
    if not thumb_path or not os.path.exists(thumb_path):
        return jsonify({"status": "error", "message": "No thumbnail found"}), 404

    return send_file(thumb_path, mimetype="image/jpeg")


KNOWN_PHOTO_APPS = [
    ("Adobe Lightroom Classic", "/Applications/Adobe Lightroom Classic/Adobe Lightroom Classic.app"),
    ("Adobe Photoshop", "/Applications/Adobe Photoshop 2025/Adobe Photoshop 2025.app"),
    ("Adobe Photoshop", "/Applications/Adobe Photoshop 2024/Adobe Photoshop 2024.app"),
    ("Adobe Bridge", "/Applications/Adobe Bridge 2025/Adobe Bridge 2025.app"),
    ("Adobe Bridge", "/Applications/Adobe Bridge 2024/Adobe Bridge 2024.app"),
    ("Affinity Photo 2", "/Applications/Affinity Photo 2.app"),
    ("Capture One", "/Applications/Capture One.app"),
    ("DxO PhotoLab", "/Applications/DxO PhotoLab 8.app"),
    ("DxO PhotoLab", "/Applications/DxO PhotoLab 7.app"),
    ("Photos", "/Applications/Photos.app"),
    ("Preview", "/Applications/Preview.app"),
]


@api.route("/apps", methods=["GET"])
def list_apps():
    """Return a list of installed photo applications."""
    installed = []
    seen = set()
    if sys.platform == "darwin":
        for name, path in KNOWN_PHOTO_APPS:
            if name not in seen and os.path.exists(path):
                installed.append({"name": name, "path": path})
                seen.add(name)
    return jsonify({"status": "ok", "apps": installed})


@api.route("/open", methods=["POST"])
def open_file():
    """Open or reveal a photo file on the local machine."""
    data = request.get_json()
    if not data or "path" not in data:
        return jsonify({"status": "error", "message": "Missing 'path'"}), 400

    file_path = data["path"]
    action = data.get("action", "open")
    app_path = data.get("app")

    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "File not found"}), 404

    try:
        if sys.platform == "darwin":
            if action == "reveal":
                subprocess.Popen(["open", "-R", file_path])
            elif app_path:
                subprocess.Popen(["open", "-a", app_path, file_path])
            else:
                subprocess.Popen(["open", file_path])
        elif sys.platform == "win32":
            if action == "reveal":
                subprocess.Popen(["explorer", "/select,", file_path])
            else:
                os.startfile(file_path)
        else:
            subprocess.Popen(["xdg-open", file_path])

        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
