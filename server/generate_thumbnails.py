#!/usr/bin/env python3
"""Generate stored thumbnails for existing indexed photos.

Walks all metadata JSON files in the index, reads each photo's original file,
generates a smaller JPEG thumbnail, and saves it alongside the metadata.

Usage:
    python generate_thumbnails.py --index-folder /path/to/index
    python generate_thumbnails.py --index-folder /path/to/index --size 256
    python generate_thumbnails.py --index-folder /path/to/index --dry-run
    python generate_thumbnails.py --index-folder /path/to/index --force
"""

import argparse
import hashlib
import io
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RAW_EXTENSIONS = {
    ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf",
    ".rw2", ".dng", ".pef", ".srw", ".x3f",
}


def make_thumbnail(image_path, max_size=512, quality=85):
    """Generate a JPEG thumbnail from an image file."""
    from PIL import Image

    ext = os.path.splitext(image_path)[1].lower()
    if ext in RAW_EXTENSIONS:
        import rawpy

        with rawpy.imread(image_path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True)
        img = Image.fromarray(rgb)
    else:
        img = Image.open(image_path)

    img.thumbnail((max_size, max_size))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def thumbnail_path_for_metadata(json_path):
    """Swap .json extension to .jpg for the thumbnail path."""
    return json_path.rsplit(".json", 1)[0] + ".jpg"


def main():
    parser = argparse.ArgumentParser(
        description="Generate stored thumbnails for existing indexed photos."
    )
    parser.add_argument("--index-folder", required=True,
                        help="Path to the index folder")
    parser.add_argument("--size", type=int, default=512,
                        help="Max thumbnail dimension in pixels (default: 512)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be generated without writing files")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing thumbnails")
    args = parser.parse_args()

    metadata_dir = os.path.join(args.index_folder, "metadata")
    if not os.path.isdir(metadata_dir):
        logger.error(f"No metadata directory found at {metadata_dir}")
        sys.exit(1)

    generated = 0
    skipped = 0
    errors = 0

    for shard in sorted(os.listdir(metadata_dir)):
        shard_path = os.path.join(metadata_dir, shard)
        if not os.path.isdir(shard_path):
            continue
        for fname in sorted(os.listdir(shard_path)):
            if not fname.endswith(".json"):
                continue

            json_path = os.path.join(shard_path, fname)
            thumb_path = thumbnail_path_for_metadata(json_path)

            if os.path.exists(thumb_path) and not args.force:
                skipped += 1
                continue

            try:
                with open(json_path, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read {json_path}: {e}")
                errors += 1
                continue

            image_path = data.get("image_path", "")
            if not image_path:
                logger.warning(f"No image_path in {json_path}")
                errors += 1
                continue

            if not os.path.exists(image_path):
                logger.warning(f"Original file not found: {image_path}")
                errors += 1
                continue

            if args.dry_run:
                logger.info(f"[DRY RUN] Would generate thumbnail for {os.path.basename(image_path)}")
                generated += 1
                continue

            try:
                jpeg_bytes = make_thumbnail(image_path, max_size=args.size)
                with open(thumb_path, "wb") as f:
                    f.write(jpeg_bytes)
                generated += 1
                logger.info(f"Generated: {os.path.basename(image_path)} ({len(jpeg_bytes)} bytes)")
            except Exception as e:
                logger.warning(f"Failed to generate thumbnail for {image_path}: {e}")
                errors += 1

    logger.info(f"\n{'=== DRY RUN ' if args.dry_run else '=== '}SUMMARY ===")
    logger.info(f"  Generated: {generated}")
    logger.info(f"  Skipped (already exist): {skipped}")
    logger.info(f"  Errors: {errors}")

    if errors > 0:
        logger.warning("Some thumbnails could not be generated. Fix file access issues and re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
