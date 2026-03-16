import base64
import logging

import requests

from config import config

logger = logging.getLogger(__name__)


def describe_image(image_path_on_disk):
    if config["vision_mode"] == "openai":
        return _describe_image_openai(image_path_on_disk)
    return _describe_image_ollama(image_path_on_disk)


def _describe_image_ollama(image_path_on_disk):
    with open(image_path_on_disk, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = f"{config['ollama_vision_endpoint']}/api/chat"
    payload = {
        "model": config["ollama_vision_model"],
        "messages": [
            {
                "role": "user",
                "content": "Describe this image in detail. Include subjects, actions, colors, composition, and any text visible.",
                "images": [image_b64],
            }
        ],
        "stream": False,
    }
    resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "")


def _describe_image_openai(image_path_on_disk):
    with open(image_path_on_disk, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    api_key = config["openai_vision_api_key"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Describe this image in detail. Include subjects, actions, colors, composition, and any text visible.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                ],
            }
        ],
        "stream": False,
    }
    resp = requests.post("https://api.openai.com/v1/chat/completions",
                         headers=headers, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]
