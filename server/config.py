import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "lrcembedindex_config.json"

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
}


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
    path = get_config_path()
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        safe = {k: v for k, v in config.items() if "api_key" not in k}
        with open(path, "w") as f:
            json.dump(safe, f, indent=2)
        logger.info(f"Config saved to {path}")


def load_config():
    home_config = os.path.join(str(Path.home()), ".lrcembedindex_last_config.json")
    if os.path.exists(home_config):
        with open(home_config, "r") as f:
            last = json.load(f)
        if last.get("index_folder"):
            config.update(last)
            cfg_path = get_config_path()
            if cfg_path and os.path.exists(cfg_path):
                with open(cfg_path, "r") as f:
                    saved = json.load(f)
                config.update(saved)
            logger.info(f"Loaded config from {home_config}")
            return True
    return False


def save_last_config_pointer():
    home_config = os.path.join(str(Path.home()), ".lrcembedindex_last_config.json")
    with open(home_config, "w") as f:
        json.dump(config, f, indent=2)
