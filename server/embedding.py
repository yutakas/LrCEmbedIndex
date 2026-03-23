import logging

import requests

from config import config
from ollama_lock import ollama_cooldown, ollama_lock

logger = logging.getLogger(__name__)


def get_embedding(text):
    if config["embed_mode"] == "openai":
        return _get_embedding_openai(text)
    if config["embed_mode"] == "voyage":
        return _get_embedding_voyage(text)
    return _get_embedding_ollama(text)


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
