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
    "patrol_start_time": "",    # HH:MM 24h format, empty = no restriction
    "patrol_end_time": "",      # HH:MM 24h format, empty = no restriction
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


# Mapping from environment variable names to config keys and their types.
# Types: str, int, bool
_ENV_MAP = {
    "INDEX_FOLDER":             ("index_folder", str),
    "VISION_MODE":              ("vision_mode", str),
    "OLLAMA_VISION_ENDPOINT":   ("ollama_vision_endpoint", str),
    "OLLAMA_VISION_MODEL":      ("ollama_vision_model", str),
    "OPENAI_VISION_API_KEY":    ("openai_vision_api_key", str),
    "OPENAI_VISION_MODEL":      ("openai_vision_model", str),
    "CLAUDE_VISION_API_KEY":    ("claude_vision_api_key", str),
    "CLAUDE_VISION_MODEL":      ("claude_vision_model", str),
    "EMBED_MODE":               ("embed_mode", str),
    "OLLAMA_EMBED_ENDPOINT":    ("ollama_embed_endpoint", str),
    "OLLAMA_EMBED_MODEL":       ("ollama_embed_model", str),
    "OPENAI_EMBED_API_KEY":     ("openai_embed_api_key", str),
    "OPENAI_EMBED_MODEL":       ("openai_embed_model", str),
    "VOYAGE_EMBED_API_KEY":     ("voyage_embed_api_key", str),
    "VOYAGE_EMBED_MODEL":       ("voyage_embed_model", str),
    "SEARCH_MAX_RESULTS":       ("search_max_results", int),
    "SEARCH_RELEVANCE":         ("search_relevance", int),
    "THUMBNAIL_STORE_SIZE":     ("thumbnail_store_size", int),
    "STRIP_GPS_FOR_CLOUD":      ("strip_gps_for_cloud", bool),
    "DEBUG_LOGGING":            ("debug_logging", bool),
    "PATROL_ENABLED":           ("patrol_enabled", bool),
    "PATROL_INTERVAL_MINUTES":  ("patrol_interval_minutes", int),
    "PATROL_BATCH_SIZE":        ("patrol_batch_size", int),
    "PATROL_START_TIME":        ("patrol_start_time", str),
    "PATROL_END_TIME":          ("patrol_end_time", str),
}


def _apply_env_overrides():
    """Apply environment variables to config (overrides saved JSON config)."""
    applied = []
    for env_name, (cfg_key, typ) in _ENV_MAP.items():
        val = os.environ.get(env_name)
        if not val:
            continue
        if typ is bool:
            config[cfg_key] = val.lower() in ("true", "1", "yes")
        elif typ is int:
            try:
                config[cfg_key] = int(val)
            except ValueError:
                logger.warning(f"Invalid integer for {env_name}: {val}")
                continue
        else:
            config[cfg_key] = val
        applied.append(env_name)

    if applied:
        logger.info(f"Config from environment: {', '.join(applied)}")
        for env_name in applied:
            cfg_key = _ENV_MAP[env_name][0]
            logger.debug(f"  {env_name} -> {cfg_key}={config[cfg_key]}")


def _apply_photo_folder_default():
    """Default patrol_folders to PHOTO_FOLDER env var if empty."""
    photo_folder = os.environ.get("PHOTO_FOLDER")
    if photo_folder and not config["patrol_folders"]:
        config["patrol_folders"] = [photo_folder]
        logger.info(f"patrol_folders defaulted to PHOTO_FOLDER: {photo_folder}")


def load_config():
    """Load config from disk. Encrypted API key fields are decrypted.

    Precedence (highest wins): environment variables > JSON config file > defaults.
    """
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
                # Env vars override saved JSON (standard 12-factor convention)
                _apply_env_overrides()
                _apply_photo_folder_default()
                return True

        # No JSON config found — env overrides are the active config
        _apply_env_overrides()
        _apply_photo_folder_default()
        if config.get("index_folder"):
            logger.info("Config initialized from environment variables")
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
