#!/usr/bin/env python3
"""Scan a directory for photo files and index them via the LrCEmbedIndex server.

Generates JPEG thumbnails (max 1024px) and extracts EXIF metadata, then
POSTs each photo to the /index endpoint — the same flow as the Lightroom
plugin but without requiring Lightroom.

Usage:
    python scan_and_index.py /path/to/photos
    python scan_and_index.py /path/to/photos --server http://localhost:8600
    python scan_and_index.py /path/to/photos --dry-run
    python scan_and_index.py /path/to/photos --extensions .jpg .arw .dng
    python scan_and_index.py /path/to/photos \\
        --index-folder /path/to/index \\
        --ollama-vision-model qwen3.5 \\
        --ollama-embed-model nomic-embed-text
"""

import argparse
import json
import logging
import os
import sys
from urllib.parse import quote

import requests

from photo_utils import (
    find_photos, make_thumbnail, extract_exif, extract_exif_raw,
    DEFAULT_EXTENSIONS, RAW_EXTENSIONS,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SERVER = "http://localhost:8600"
TIMEOUT = 1000


def configure_server(server_url, settings):
    """POST settings to /settings endpoint. Returns True on success."""
    if not settings:
        return True
    try:
        resp = requests.post(
            f"{server_url}/settings",
            json=settings,
            timeout=30,
        )
        result = resp.json()
        if result.get("status") == "ok":
            logger.info("Server settings updated successfully")
            return True
        else:
            logger.error(f"Failed to update settings: {result.get('message', 'unknown')}")
            return False
    except requests.ConnectionError:
        logger.error(f"Cannot connect to server at {server_url}")
        return False
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        return False


def index_photo(server_url, image_path, jpeg_data, exif_data):
    """POST a photo to the /index endpoint."""
    exif_json = json.dumps(exif_data)
    exif_encoded = quote(exif_json, safe="")

    headers = {
        "Content-Type": "image/jpeg",
        "X-Image-Path": image_path,
        "X-Exif-Data": exif_encoded,
    }

    resp = requests.post(
        f"{server_url}/index",
        data=jpeg_data,
        headers=headers,
        timeout=TIMEOUT,
    )
    return resp.json()


def build_settings(args):
    """Build a settings dict from CLI args, omitting unset values."""
    mapping = {
        "index_folder": args.index_folder,
        "vision_mode": args.vision_mode,
        "ollama_vision_endpoint": args.ollama_vision_endpoint,
        "ollama_vision_model": args.ollama_vision_model,
        "openai_vision_api_key": args.openai_vision_api_key,
        "openai_vision_model": args.openai_vision_model,
        "claude_vision_api_key": args.claude_vision_api_key,
        "claude_vision_model": args.claude_vision_model,
        "embed_mode": args.embed_mode,
        "ollama_embed_endpoint": args.ollama_embed_endpoint,
        "ollama_embed_model": args.ollama_embed_model,
        "openai_embed_api_key": args.openai_embed_api_key,
        "openai_embed_model": args.openai_embed_model,
        "voyage_embed_api_key": args.voyage_embed_api_key,
        "voyage_embed_model": args.voyage_embed_model,
    }
    return {k: v for k, v in mapping.items() if v is not None}


def main():
    parser = argparse.ArgumentParser(
        description="Scan a directory for photos and index them via the LrCEmbedIndex server."
    )
    parser.add_argument("directory", help="Directory to scan for photo files")
    parser.add_argument("--server", default=DEFAULT_SERVER,
                        help=f"Server URL (default: {DEFAULT_SERVER})")
    parser.add_argument("--extensions", nargs="+",
                        help="File extensions to include (e.g. .jpg .arw .dng)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List photos that would be indexed without sending them")

    # Server settings (sent to /settings before indexing)
    settings_group = parser.add_argument_group("server settings",
        "Configure the server before indexing. All optional — omitted values keep current config.")
    settings_group.add_argument("--index-folder", help="Index folder path")
    settings_group.add_argument("--vision-mode", choices=["ollama", "openai", "claude"],
                                help="Vision model provider")
    settings_group.add_argument("--ollama-vision-endpoint", help="Ollama vision endpoint URL")
    settings_group.add_argument("--ollama-vision-model", help="Ollama vision model name")
    settings_group.add_argument("--openai-vision-api-key", help="OpenAI vision API key")
    settings_group.add_argument("--openai-vision-model", help="OpenAI vision model name")
    settings_group.add_argument("--claude-vision-api-key", help="Claude vision API key")
    settings_group.add_argument("--claude-vision-model", help="Claude vision model name")
    settings_group.add_argument("--embed-mode", choices=["ollama", "openai", "voyage"],
                                help="Embedding model provider")
    settings_group.add_argument("--ollama-embed-endpoint", help="Ollama embed endpoint URL")
    settings_group.add_argument("--ollama-embed-model", help="Ollama embedding model name")
    settings_group.add_argument("--openai-embed-api-key", help="OpenAI embed API key")
    settings_group.add_argument("--openai-embed-model", help="OpenAI embedding model name")
    settings_group.add_argument("--voyage-embed-api-key", help="Voyage AI API key")
    settings_group.add_argument("--voyage-embed-model", help="Voyage AI embedding model name")

    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        logger.error(f"Not a directory: {args.directory}")
        sys.exit(1)

    extensions = DEFAULT_EXTENSIONS
    if args.extensions:
        extensions = {e if e.startswith(".") else f".{e}" for e in args.extensions}

    # Configure server settings if any were provided
    settings = build_settings(args)
    if settings and not args.dry_run:
        if not configure_server(args.server, settings):
            sys.exit(1)

    logger.info(f"Scanning: {args.directory}")
    photos = find_photos(args.directory, extensions)
    logger.info(f"Found {len(photos)} photo(s)")

    if not photos:
        return

    if args.dry_run:
        for p in photos:
            logger.info(f"  [DRY RUN] {p}")
        if settings:
            logger.info(f"\n  Settings that would be applied: {json.dumps(settings, indent=2)}")
        return

    success = 0
    errors = 0

    for i, photo_path in enumerate(photos, 1):
        basename = os.path.basename(photo_path)
        logger.info(f"[{i}/{len(photos)}] {basename}")

        try:
            jpeg_data = make_thumbnail(photo_path)
        except Exception as e:
            logger.warning(f"  Thumbnail failed: {e}")
            errors += 1
            continue

        ext = os.path.splitext(photo_path)[1].lower()
        if ext in RAW_EXTENSIONS:
            exif_data = extract_exif_raw(photo_path)
        else:
            exif_data = extract_exif(photo_path)

        try:
            result = index_photo(args.server, photo_path, jpeg_data, exif_data)
            if result.get("status") == "ok":
                skip_info = ""
                if result.get("skipped_vision"):
                    skip_info += " (vision cached)"
                if result.get("skipped_embed"):
                    skip_info += " (embed cached)"
                desc_preview = result.get("description", "")[:100]
                if desc_preview:
                    logger.info(f"  {desc_preview}...")
                logger.info(f"  OK in {result.get('elapsed', '?')}s{skip_info}")
                success += 1
            else:
                logger.warning(f"  Server error: {result.get('message', 'unknown')}")
                errors += 1
        except requests.ConnectionError:
            logger.error(f"  Cannot connect to server at {args.server}")
            logger.error("  Is the server running? Start it with: python server/server.py")
            sys.exit(1)
        except Exception as e:
            logger.warning(f"  Failed: {e}")
            errors += 1

    logger.info(f"\nDone: {success} indexed, {errors} errors")


if __name__ == "__main__":
    main()
