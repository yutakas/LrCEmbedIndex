import json
import logging
import os
import threading
from pathlib import Path

from keystore import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "lrcembedindex_config.json"

# Thread-safe access to config dict
_config_lock = threading.RLock()

# Keys that contain API secrets and must be encrypted on disk
API_KEY_FIELDS = {
    "openai_vision_api_key",
    "openai_embed_api_key",
    "claude_vision_api_key",
    "voyage_embed_api_key",
}

config = {
    "index_folder": "",

    # Vision model settings
    "vision_mode": "ollama",
    "ollama_vision_endpoint": "http://localhost:11434",
    "ollama_vision_model": "qwen3.5",
    "openai_vision_api_key": "",
    "openai_vision_model": "gpt-4o",
    "claude_vision_api_key": "",
    "claude_vision_model": "claude-sonnet-4-6",

    # Embedding model settings
    "embed_mode": "ollama",
    "ollama_embed_endpoint": "http://localhost:11434",
    "ollama_embed_model": "nomic-embed-text",
    "openai_embed_api_key": "",
    "openai_embed_model": "text-embedding-3-small",
    "voyage_embed_api_key": "",
    "voyage_embed_model": "voyage-3.5",

    # Search settings
    "search_max_results": 10,
    "search_relevance": 50,  # 0 = show all, 100 = only very close matches

    # Thumbnail settings
    "thumbnail_store_size": 512,  # max dimension in px for stored thumbnails (0 = disable)

    # Privacy settings
    "strip_gps_for_cloud": True,  # strip GPS from EXIF before sending to cloud APIs

    # Debug settings
    "debug_logging": False,

    # Patrol settings
    "patrol_enabled": False,
    "patrol_folders": [],       # list of {"path": str, "recursive": bool}
    "patrol_interval_minutes": 5,
    "patrol_batch_size": 10,    # photos to process per batch before checking for interrupts
}

VERSION = "1.2.0"


def get_vision_model_label():
    if config["vision_mode"] == "openai":
        return f"openai:{config['openai_vision_model']}"
    if config["vision_mode"] == "claude":
        return f"claude:{config['claude_vision_model']}"
    return f"ollama:{config['ollama_vision_model']}"


def get_embed_model_label():
    if config["embed_mode"] == "openai":
        return f"openai:{config['openai_embed_model']}"
    if config["embed_mode"] == "voyage":
        return f"voyage:{config['voyage_embed_model']}"
    return f"ollama:{config['ollama_embed_model']}"


def get_config_path():
    if config["index_folder"]:
        return os.path.join(config["index_folder"], CONFIG_FILENAME)
    return None


def save_config():
    """Save config to disk. API key fields are encrypted."""
    with _config_lock:
        path = get_config_path()
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            disk_config = {}
            for k, v in config.items():
                if k in API_KEY_FIELDS:
                    disk_config[k] = encrypt_value(v) if v else ""
                else:
                    disk_config[k] = v
            with open(path, "w") as f:
                json.dump(disk_config, f, indent=2)
            logger.info(f"Config saved to {path}")


def load_config():
    """Load config from disk. Encrypted API key fields are decrypted."""
    with _config_lock:
        home_config = os.path.join(str(Path.home()), ".lrcembedindex_last_config.json")
        if os.path.exists(home_config):
            with open(home_config, "r") as f:
                last = json.load(f)
            if last.get("index_folder"):
                # Decrypt any encrypted values from home config
                for k in API_KEY_FIELDS:
                    if k in last:
                        last[k] = decrypt_value(last[k])
                config.update(last)
                cfg_path = get_config_path()
                if cfg_path and os.path.exists(cfg_path):
                    with open(cfg_path, "r") as f:
                        saved = json.load(f)
                    # Decrypt any encrypted values from saved config
                    for k in API_KEY_FIELDS:
                        if k in saved:
                            saved[k] = decrypt_value(saved[k])
                    config.update(saved)
                logger.info(f"Loaded config from {home_config}")
                return True
        return False


def save_last_config_pointer():
    """Save a pointer config to home directory. API keys are encrypted."""
    with _config_lock:
        home_config = os.path.join(str(Path.home()), ".lrcembedindex_last_config.json")
        disk_config = {}
        for k, v in config.items():
            if k in API_KEY_FIELDS:
                disk_config[k] = encrypt_value(v) if v else ""
            else:
                disk_config[k] = v
        with open(home_config, "w") as f:
            json.dump(disk_config, f, indent=2)
