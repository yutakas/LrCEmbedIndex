import hashlib
import json
import os
from datetime import datetime, timezone

from config import config

METADATA_DIR_NAME = "metadata"


def get_metadata_dir():
    if config["index_folder"]:
        return os.path.join(config["index_folder"], METADATA_DIR_NAME)
    return None


def metadata_path_for_image(image_path):
    md5 = hashlib.md5(image_path.encode("utf-8")).hexdigest()
    meta_dir = get_metadata_dir()
    if not meta_dir:
        return None
    return os.path.join(meta_dir, md5[:2], f"{md5}.json")


def load_photo_metadata(image_path):
    path = metadata_path_for_image(image_path)
    if path and os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_photo_metadata(image_path, data):
    path = metadata_path_for_image(image_path)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data["image_path"] = image_path
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def get_vision_result(meta, vision_label):
    """Return the vision result dict for the given model, or None."""
    if not meta:
        return None
    return meta.get("vision_results", {}).get(vision_label)


def set_vision_result(meta, vision_label, description, exif_data, full_description):
    """Store a vision result under the model label with a timestamp.

    Embeddings are nested inside vision_results[vision_label]["embeddings"]
    because an embedding depends on the description produced by a specific
    vision model.
    """
    if "vision_results" not in meta:
        meta["vision_results"] = {}

    # Preserve existing embeddings if the vision entry already exists
    existing_embeds = {}
    if vision_label in meta["vision_results"]:
        existing_embeds = meta["vision_results"][vision_label].get("embeddings", {})

    meta["vision_results"][vision_label] = {
        "vision_description": description,
        "full_description": full_description,
        "exif": exif_data,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "embeddings": existing_embeds,
    }


def get_embed_result(meta, vision_label, embed_label):
    """Return the embed result for a given vision+embed model pair, or None."""
    if not meta:
        return None
    vision = meta.get("vision_results", {}).get(vision_label)
    if not vision:
        return None
    return vision.get("embeddings", {}).get(embed_label)


def set_embed_result(meta, vision_label, embed_label, embedding, description_used):
    """Store an embed result nested under the vision result."""
    vision = meta.get("vision_results", {}).get(vision_label)
    if not vision:
        return
    if "embeddings" not in vision:
        vision["embeddings"] = {}
    vision["embeddings"][embed_label] = {
        "embedding": embedding,
        "description_used": description_used,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def count_metadata_files():
    meta_dir = get_metadata_dir()
    if not meta_dir or not os.path.exists(meta_dir):
        return 0
    count = 0
    for shard in os.listdir(meta_dir):
        shard_path = os.path.join(meta_dir, shard)
        if os.path.isdir(shard_path):
            count += len([f for f in os.listdir(shard_path) if f.endswith(".json")])
    return count
