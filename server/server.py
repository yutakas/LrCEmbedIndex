import hashlib
import json
import os
import sys
import tempfile
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, request, jsonify
import chromadb

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
CONFIG_FILENAME = "lrcembedindex_config.json"
METADATA_DIR_NAME = "metadata"
CHROMA_DIR_NAME = "chromadb"

VISION_MODEL = "qwen3.5"
EMBED_MODEL = "nomic-embed-text"

config = {
    "index_folder": "",
    "ollama_url": "http://localhost:11434",
}
chroma_client = None
chroma_collection = None


def get_config_path():
    """Return the path to the config file in the index folder."""
    if config["index_folder"]:
        return os.path.join(config["index_folder"], CONFIG_FILENAME)
    return None


def get_metadata_dir():
    """Return the path to the metadata directory."""
    if config["index_folder"]:
        return os.path.join(config["index_folder"], METADATA_DIR_NAME)
    return None


def metadata_path_for_image(image_path):
    """Return the sharded JSON file path for a given image path.

    Structure: metadata/<first 2 hex chars>/<full md5 hex>.json
    This distributes up to 256 subdirectories, each holding many files.
    """
    md5 = hashlib.md5(image_path.encode("utf-8")).hexdigest()
    meta_dir = get_metadata_dir()
    if not meta_dir:
        return None
    return os.path.join(meta_dir, md5[:2], f"{md5}.json")


def get_chroma_path():
    """Return the path to the ChromaDB directory."""
    if config["index_folder"]:
        return os.path.join(config["index_folder"], CHROMA_DIR_NAME)
    return None


def save_config():
    """Save current config to the index folder."""
    path = get_config_path()
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"Config saved to {path}")


def load_config():
    """Try to load config from a well-known location."""
    # Check for last-used config path
    home_config = os.path.join(str(Path.home()), ".lrcembedindex_last_config.json")
    if os.path.exists(home_config):
        with open(home_config, "r") as f:
            last = json.load(f)
        if last.get("index_folder"):
            config["index_folder"] = last["index_folder"]
            config["ollama_url"] = last.get("ollama_url", config["ollama_url"])
            cfg_path = get_config_path()
            if cfg_path and os.path.exists(cfg_path):
                with open(cfg_path, "r") as f:
                    saved = json.load(f)
                config.update(saved)
            logger.info(f"Loaded config from {home_config}")
            return True
    return False


def save_last_config_pointer():
    """Save a pointer to the current config location in home directory."""
    home_config = os.path.join(str(Path.home()), ".lrcembedindex_last_config.json")
    with open(home_config, "w") as f:
        json.dump({
            "index_folder": config["index_folder"],
            "ollama_url": config["ollama_url"],
        }, f, indent=2)


def load_photo_metadata(image_path):
    """Load metadata JSON for a single photo. Returns dict or None."""
    path = metadata_path_for_image(image_path)
    if path and os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_photo_metadata(image_path, data):
    """Save metadata JSON for a single photo to its sharded location."""
    path = metadata_path_for_image(image_path)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data["image_path"] = image_path
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def count_metadata_files():
    """Count total metadata JSON files across all shards."""
    meta_dir = get_metadata_dir()
    if not meta_dir or not os.path.exists(meta_dir):
        return 0
    count = 0
    for shard in os.listdir(meta_dir):
        shard_path = os.path.join(meta_dir, shard)
        if os.path.isdir(shard_path):
            count += len([f for f in os.listdir(shard_path) if f.endswith(".json")])
    return count


def init_chromadb():
    """Initialize or load ChromaDB from the index folder."""
    global chroma_client, chroma_collection
    chroma_path = get_chroma_path()
    if not chroma_path:
        logger.warning("No index folder set, cannot initialize ChromaDB")
        return
    os.makedirs(chroma_path, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=chroma_path)
    chroma_collection = chroma_client.get_or_create_collection(
        name="photo_index",
        metadata={"hnsw:space": "cosine"},
    )
    logger.info(f"ChromaDB initialized at {chroma_path}, collection count: {chroma_collection.count()}")


def call_ollama_generate(image_path_on_disk, model="qwen3.5"):
    """Call Ollama with an image to get a description using a vision model."""
    import base64

    with open(image_path_on_disk, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = f"{config['ollama_url']}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Describe this image in detail. Include subjects, actions, colors, composition, and any text visible.",
                "images": [image_b64],
            }
        ],
        "stream": False,
    }
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "")


def call_ollama_embed(text, model="nomic-embed-text"):
    """Call Ollama to get an embedding vector for text."""
    url = f"{config['ollama_url']}/api/embeddings"
    payload = {
        "model": model,
        "prompt": text,
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    embedding = data.get("embedding")
    if embedding:
        return embedding
    return None


def exif_to_text(exif_data):
    """Convert EXIF dict to a human-readable text block for embedding."""
    parts = []
    field_map = {
        "cameraMake": "Camera Make",
        "cameraModel": "Camera Model",
        "lens": "Lens",
        "focalLength": "Focal Length",
        "aperture": "Aperture",
        "shutterSpeed": "Shutter Speed",
        "isoSpeedRating": "ISO",
        "exposureBias": "Exposure Bias",
        "dateTimeOriginal": "Date Taken",
        "gps": "GPS Location",
        "fileName": "File Name",
        "fileType": "File Type",
        "dimensions": "Dimensions",
        "title": "Title",
        "caption": "Caption",
        "keywords": "Keywords",
        "label": "Label",
        "rating": "Rating",
    }
    for key, label in field_map.items():
        val = exif_data.get(key, "")
        if val and str(val).strip():
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


def sanitize_chroma_id(path):
    """Create a valid ChromaDB ID from a file path."""
    return path.replace("/", "__").replace("\\", "__").replace(" ", "_")


@app.route("/index", methods=["POST"])
def index_photo():
    """
    Receive a JPEG image and the original file path, generate description
    and embedding via Ollama, and store in metadata + ChromaDB.
    """
    try:
        image_path = request.headers.get("X-Image-Path", "")
        if not image_path:
            return jsonify({"status": "error", "message": "Missing X-Image-Path header"}), 400

        if not config["index_folder"]:
            return jsonify({"status": "error", "message": "Index folder not configured"}), 500

        # Parse EXIF data from header
        exif_json_str = request.headers.get("X-Exif-Data", "{}")
        try:
            exif_data = json.loads(exif_json_str)
        except json.JSONDecodeError:
            exif_data = {}

        # Save incoming JPEG to a temp file
        jpeg_data = request.get_data()
        if not jpeg_data:
            return jsonify({"status": "error", "message": "No image data received"}), 400

        # Check existing metadata — skip if already processed with same models
        existing = load_photo_metadata(image_path)
        if (existing
                and existing.get("vision_model") == VISION_MODEL
                and existing.get("embed_model") == EMBED_MODEL
                and existing.get("description")):
            logger.info(f"Skipping {image_path} — already indexed with {VISION_MODEL}/{EMBED_MODEL}")
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
            logger.info(f"Generating description for {image_path}")
            vision_description = call_ollama_generate(tmp_path)
            logger.info(f"Description: {vision_description[:100]}...")

            # Append EXIF info to description for richer embedding
            exif_text = exif_to_text(exif_data)
            if exif_text:
                description = vision_description + "\n\n--- Photo Metadata ---\n" + exif_text
            else:
                description = vision_description

            # Get embedding from combined description
            logger.info(f"Generating embedding for {image_path}")
            embedding = call_ollama_embed(description)
            if not embedding:
                return jsonify({"status": "error", "message": "Failed to generate embedding"}), 500

            # Store in metadata (one JSON file per photo, sharded)
            save_photo_metadata(image_path, {
                "description": description,
                "vision_description": vision_description,
                "exif": exif_data,
                "embedding": embedding,
                "vision_model": VISION_MODEL,
                "embed_model": EMBED_MODEL,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })

            # Store/update in ChromaDB
            if chroma_collection is None:
                init_chromadb()

            doc_id = sanitize_chroma_id(image_path)
            chroma_collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[description],
                metadatas=[{"path": image_path}],
            )

            logger.info(f"Indexed {image_path} successfully")
            return jsonify({"status": "ok", "description": description})

        finally:
            os.unlink(tmp_path)

    except Exception as e:
        logger.exception(f"Error indexing photo: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/search", methods=["POST"])
def search_photo():
    """
    Search for photos matching a text query. Returns top 10 closest matches.
    """
    try:
        data = request.get_json()
        if not data or "query" not in data:
            return jsonify({"status": "error", "message": "Missing query"}), 400

        query = data["query"]

        if chroma_collection is None or chroma_collection.count() == 0:
            return jsonify({"status": "ok", "results": [], "message": "No indexed photos yet"})

        # Get embedding for the search query
        embedding = call_ollama_embed(query)
        if not embedding:
            return jsonify({"status": "error", "message": "Failed to generate query embedding"}), 500

        # Search ChromaDB
        n_results = min(10, chroma_collection.count())
        results = chroma_collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
        )

        # Format results
        matches = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                path = results["metadatas"][0][i].get("path", "") if results["metadatas"] else ""
                description = results["documents"][0][i] if results["documents"] else ""
                distance = results["distances"][0][i] if results["distances"] else 0
                matches.append({
                    "path": path,
                    "description": description,
                    "distance": distance,
                })

        logger.info(f"Search for '{query}' returned {len(matches)} results")
        return jsonify({"status": "ok", "results": matches})

    except Exception as e:
        logger.exception(f"Error searching: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/settings", methods=["POST"])
def update_settings():
    """
    Update index folder path and Ollama endpoint.
    Re-initializes ChromaDB if the folder changes.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        folder_changed = False
        if "index_folder" in data and data["index_folder"] != config["index_folder"]:
            config["index_folder"] = data["index_folder"]
            folder_changed = True

        if "ollama_url" in data:
            config["ollama_url"] = data["ollama_url"]

        # Save config
        save_config()
        save_last_config_pointer()

        # Reinitialize ChromaDB if folder changed
        if folder_changed:
            init_chromadb()

        logger.info(f"Settings updated: index_folder={config['index_folder']}, ollama_url={config['ollama_url']}")
        return jsonify({"status": "ok", "config": config})

    except Exception as e:
        logger.exception(f"Error updating settings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def startup():
    """Load saved config and initialize on startup."""
    if load_config():
        if config["index_folder"]:
            init_chromadb()
            logger.info(f"Startup: {count_metadata_files()} metadata files found")


if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=8600, debug=False)
