import hashlib
import json
import os

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
