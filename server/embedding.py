import json
import logging

import requests

from config import config
from ollama_lock import ollama_cooldown, ollama_lock

logger = logging.getLogger(__name__)


def get_embedding(text):
    if config["embed_mode"] == "openai":
        vec = _get_embedding_openai(text)
    elif config["embed_mode"] == "voyage":
        vec = _get_embedding_voyage(text)
    else:
        vec = _get_embedding_ollama(text)

    if vec and logger.isEnabledFor(logging.DEBUG):
        norm = sum(v * v for v in vec) ** 0.5
        model = config.get(f"{config['embed_mode']}_embed_model",
                           config.get("ollama_embed_model", "?"))
        logger.debug(f"Embedding: mode={config['embed_mode']}, model={model}, "
                     f"dims={len(vec)}, norm={norm:.4f}, "
                     f"text={repr(text[:200])}")
        logger.debug(f"Embedding vector: {json.dumps([round(v, 6) for v in vec])}")
    return vec


def _get_embedding_ollama(text):
    url = f"{config['ollama_embed_endpoint']}/api/embeddings"
    payload = {
        "model": config["ollama_embed_model"],
        "prompt": text,
    }
    with ollama_lock:
        ollama_cooldown()
        resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return data.get("embedding")


def _get_embedding_openai(text):
    api_key = config["openai_embed_api_key"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["openai_embed_model"],
        "input": text,
    }
    resp = requests.post("https://api.openai.com/v1/embeddings",
                         headers=headers, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return data["data"][0]["embedding"]


def _get_embedding_voyage(text):
    api_key = config["voyage_embed_api_key"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["voyage_embed_model"],
        "input": [text],
        "input_type": "document",
    }
    resp = requests.post("https://api.voyageai.com/v1/embeddings",
                         headers=headers, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return data["data"][0]["embedding"]
