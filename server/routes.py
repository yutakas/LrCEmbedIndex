import json
import logging
import tempfile
import os
from datetime import datetime, timezone
from urllib.parse import unquote

from flask import Blueprint, request, jsonify

from config import (config, get_vision_model_label, get_embed_model_label,
                    save_config, save_last_config_pointer)
from metadata import load_photo_metadata, save_photo_metadata
from vectorstore import init_chromadb, upsert_photo, search_photos
from vision import describe_image
from embedding import get_embedding
from helpers import exif_to_text, sanitize_chroma_id

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__)


@api.route("/index", methods=["POST"])
def index_photo():
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

        # Check existing metadata — skip if already processed with same models
        existing = load_photo_metadata(image_path)
        if (existing
                and existing.get("vision_model") == vision_label
                and existing.get("embed_model") == embed_label
                and existing.get("description")):
            logger.info(f"Skipping {image_path} — already indexed with {vision_label}/{embed_label}")
            return jsonify({
                "status": "ok",
                "skipped": True,
                "description": existing["description"],
                "processed_at": existing.get("processed_at", ""),
            })

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(jpeg_data)
            tmp_path = tmp.name

        try:
            # Get description from vision model
            logger.info(f"Generating description for {image_path} using {vision_label}")
            vision_description = describe_image(tmp_path)
            logger.info(f"Description: {vision_description[:100]}...")

            # Append EXIF info to description for richer embedding
            exif_text = exif_to_text(exif_data)
            if exif_text:
                description = vision_description + "\n\n--- Photo Metadata ---\n" + exif_text
            else:
                description = vision_description

            # Get embedding from combined description
            logger.info(f"Generating embedding for {image_path} using {embed_label}")
            embedding = get_embedding(description)
            if not embedding:
                return jsonify({"status": "error", "message": "Failed to generate embedding"}), 500

            # Store in metadata (one JSON file per photo, sharded)
            save_photo_metadata(image_path, {
                "description": description,
                "vision_description": vision_description,
                "exif": exif_data,
                "embedding": embedding,
                "vision_model": vision_label,
                "embed_model": embed_label,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })

            # Store/update in ChromaDB
            doc_id = sanitize_chroma_id(image_path)
            upsert_photo(doc_id, embedding, description, image_path)

            logger.info(f"Indexed {image_path} successfully")
            return jsonify({"status": "ok", "description": description})

        finally:
            os.unlink(tmp_path)

    except Exception as e:
        logger.exception(f"Error indexing photo: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/search", methods=["POST"])
def search_photo():
    try:
        data = request.get_json()
        if not data or "query" not in data:
            return jsonify({"status": "error", "message": "Missing query"}), 400

        query = data["query"]

        # Get embedding for the search query
        embedding = get_embedding(query)
        if not embedding:
            return jsonify({"status": "error", "message": "Failed to generate query embedding"}), 500

        max_results = config.get("search_max_results", 10)
        matches = search_photos(embedding, n_results=max_results)

        logger.info(f"Search for '{query}' returned {len(matches)} results")
        return jsonify({"status": "ok", "results": matches})

    except Exception as e:
        logger.exception(f"Error searching: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/settings", methods=["POST"])
def update_settings():
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
                     "openai_vision_api_key"):
            if key in data:
                config[key] = data[key]

        # Embedding settings
        for key in ("embed_mode", "ollama_embed_endpoint", "ollama_embed_model",
                     "openai_embed_api_key"):
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

        logger.info(f"Settings updated: vision={get_vision_model_label()}, "
                     f"embed={get_embed_model_label()}, folder={config['index_folder']}")
        return jsonify({"status": "ok", "config": {
            k: v for k, v in config.items() if "api_key" not in k
        }})

    except Exception as e:
        logger.exception(f"Error updating settings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
