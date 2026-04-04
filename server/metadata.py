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


def thumbnail_path_for_image(image_path):
    """Return the path where a stored thumbnail JPEG should live."""
    md5 = hashlib.md5(image_path.encode("utf-8")).hexdigest()
    meta_dir = get_metadata_dir()
    if not meta_dir:
        return None
    return os.path.join(meta_dir, md5[:2], f"{md5}.jpg")


def save_thumbnail(image_path, jpeg_bytes):
    """Write thumbnail JPEG bytes to the shard directory."""
    path = thumbnail_path_for_image(image_path)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(jpeg_bytes)


def load_thumbnail(image_path):
    """Return thumbnail JPEG bytes, or None if not stored."""
    path = thumbnail_path_for_image(image_path)
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def has_thumbnail(image_path):
    """Check if a stored thumbnail exists for the given image path."""
    path = thumbnail_path_for_image(image_path)
    return path is not None and os.path.exists(path)


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


def count_thumbnail_files():
    meta_dir = get_metadata_dir()
    if not meta_dir or not os.path.exists(meta_dir):
        return 0
    count = 0
    for shard in os.listdir(meta_dir):
        shard_path = os.path.join(meta_dir, shard)
        if os.path.isdir(shard_path):
            count += len([f for f in os.listdir(shard_path) if f.endswith(".jpg")])
    return count


def collect_metadata_stats():
    """Scan all metadata files and return aggregate stats.

    Returns dict with:
        vision_models:  {model_label: count}
        embed_models:   {"vision_label/embed_label": count}
        oldest_entry:   earliest processed_at ISO string
        newest_entry:   latest processed_at ISO string
    """
    meta_dir = get_metadata_dir()
    if not meta_dir or not os.path.exists(meta_dir):
        return {}

    vision_counts = {}
    embed_counts = {}
    oldest = None
    newest = None

    for shard in os.listdir(meta_dir):
        shard_path = os.path.join(meta_dir, shard)
        if not os.path.isdir(shard_path):
            continue
        for fname in os.listdir(shard_path):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(shard_path, fname), "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            vision_results = data.get("vision_results", {})
            for v_label, v_data in vision_results.items():
                vision_counts[v_label] = vision_counts.get(v_label, 0) + 1

                ts = v_data.get("processed_at")
                if ts:
                    if oldest is None or ts < oldest:
                        oldest = ts
                    if newest is None or ts > newest:
                        newest = ts

                for e_label in v_data.get("embeddings", {}):
                    pair = f"{v_label} / {e_label}"
                    embed_counts[pair] = embed_counts.get(pair, 0) + 1

                    e_ts = v_data["embeddings"][e_label].get("processed_at")
                    if e_ts:
                        if oldest is None or e_ts < oldest:
                            oldest = e_ts
                        if newest is None or e_ts > newest:
                            newest = e_ts

    thumb_count = 0
    for shard in os.listdir(meta_dir):
        shard_path = os.path.join(meta_dir, shard)
        if os.path.isdir(shard_path):
            thumb_count += len(
                [f for f in os.listdir(shard_path) if f.endswith(".jpg")]
            )

    return {
        "vision_models": vision_counts,
        "embed_models": embed_counts,
        "oldest_entry": oldest,
        "newest_entry": newest,
        "thumbnail_count": thumb_count,
    }
