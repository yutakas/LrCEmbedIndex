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
import io
import json
import logging
import os
import sys
from urllib.parse import quote

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SERVER = "http://localhost:8600"
DEFAULT_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf",
    ".rw2", ".dng", ".pef", ".srw", ".x3f",
}
MAX_THUMB_SIZE = 1024
TIMEOUT = 1000


def find_photos(directory, extensions):
    """Recursively find photo files matching the given extensions."""
    photos = []
    for root, _dirs, files in os.walk(directory):
        for fname in sorted(files):
            if os.path.splitext(fname)[1].lower() in extensions:
                photos.append(os.path.join(root, fname))
    return photos


def make_thumbnail_pillow(image_path):
    """Generate a JPEG thumbnail using Pillow (for JPEG, PNG, TIFF)."""
    from PIL import Image

    with Image.open(image_path) as img:
        img.thumbnail((MAX_THUMB_SIZE, MAX_THUMB_SIZE))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def make_thumbnail_raw(image_path):
    """Generate a JPEG thumbnail using rawpy (for RAW formats: NEF, ARW, CR2, etc.)."""
    import rawpy
    from PIL import Image

    with rawpy.imread(image_path) as raw:
        rgb = raw.postprocess(use_camera_wb=True, half_size=True)
    img = Image.fromarray(rgb)
    img.thumbnail((MAX_THUMB_SIZE, MAX_THUMB_SIZE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


RAW_EXTENSIONS = {
    ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf",
    ".rw2", ".dng", ".pef", ".srw", ".x3f",
}


def make_thumbnail(image_path):
    """Generate a JPEG thumbnail, dispatching to rawpy for RAW files."""
    ext = os.path.splitext(image_path)[1].lower()
    if ext in RAW_EXTENSIONS:
        return make_thumbnail_raw(image_path)
    return make_thumbnail_pillow(image_path)


def extract_exif(image_path):
    """Extract EXIF metadata into the same dict format the Lua plugin sends."""
    from PIL import Image
    from PIL.ExifTags import TAGS

    exif_data = {
        "fileName": os.path.basename(image_path),
        "fileType": os.path.splitext(image_path)[1].lstrip(".").upper(),
    }

    try:
        with Image.open(image_path) as img:
            exif_data["dimensions"] = f"{img.width} x {img.height}"
            raw_exif = img.getexif()
            if not raw_exif:
                return exif_data

            tag_map = {v: k for k, v in TAGS.items()}

            make = raw_exif.get(tag_map.get("Make", 0x010F), "")
            model = raw_exif.get(tag_map.get("Model", 0x0110), "")
            exif_data["cameraMake"] = str(make) if make else ""
            exif_data["cameraModel"] = str(model) if model else ""

            exif_ifd = raw_exif.get_ifd(0x8769)
            if exif_ifd:
                lens = exif_ifd.get(0xA434, "")
                exif_data["lens"] = str(lens) if lens else ""

                fl = exif_ifd.get(0x920A, "")
                if fl:
                    exif_data["focalLength"] = f"{float(fl):.0f} mm"

                aperture = exif_ifd.get(0x829D, "")
                if aperture:
                    exif_data["aperture"] = f"f/{float(aperture):.1f}"

                exposure = exif_ifd.get(0x829A, "")
                if exposure:
                    exp_val = float(exposure)
                    if exp_val < 1:
                        exif_data["shutterSpeed"] = f"1/{int(1/exp_val)} s"
                    else:
                        exif_data["shutterSpeed"] = f"{exp_val:.1f} s"

                iso = exif_ifd.get(0x8827, "")
                exif_data["isoSpeedRating"] = str(iso) if iso else ""

                bias = exif_ifd.get(0x9204, "")
                if bias:
                    exif_data["exposureBias"] = f"{float(bias):+.1f} EV"

                date = exif_ifd.get(0x9003, "")
                exif_data["dateTimeOriginal"] = str(date) if date else ""

            gps_ifd = raw_exif.get_ifd(0x8825)
            if gps_ifd:
                try:
                    lat = gps_ifd.get(2)
                    lat_ref = gps_ifd.get(1, "N")
                    lon = gps_ifd.get(4)
                    lon_ref = gps_ifd.get(3, "E")
                    if lat and lon:
                        lat_deg = float(lat[0]) + float(lat[1]) / 60 + float(lat[2]) / 3600
                        lon_deg = float(lon[0]) + float(lon[1]) / 60 + float(lon[2]) / 3600
                        if lat_ref == "S":
                            lat_deg = -lat_deg
                        if lon_ref == "W":
                            lon_deg = -lon_deg
                        exif_data["gps"] = f"{lat_deg:.6f}, {lon_deg:.6f}"
                except (TypeError, IndexError, ZeroDivisionError):
                    pass

    except Exception as e:
        logger.debug(f"EXIF extraction failed for {image_path}: {e}")

    return exif_data


def extract_exif_raw(image_path):
    """Extract basic EXIF from RAW files via rawpy/Pillow fallback."""
    exif_data = {
        "fileName": os.path.basename(image_path),
        "fileType": os.path.splitext(image_path)[1].lstrip(".").upper(),
    }
    try:
        return extract_exif(image_path)
    except Exception:
        return exif_data


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
