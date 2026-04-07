"""Shared photo utilities for file discovery, thumbnail generation, and EXIF extraction.

Used by both scan_and_index.py (CLI) and patrol.py (background worker).
"""

import io
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf",
    ".rw2", ".dng", ".pef", ".srw", ".x3f",
}

RAW_EXTENSIONS = {
    ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf",
    ".rw2", ".dng", ".pef", ".srw", ".x3f",
}

MAX_THUMB_SIZE = 1024


def find_photos(directory, extensions=None):
    """Recursively find photo files matching the given extensions."""
    if extensions is None:
        extensions = DEFAULT_EXTENSIONS
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
                    if exp_val > 0 and exp_val < 1:
                        exif_data["shutterSpeed"] = f"1/{int(1/exp_val)} s"
                    elif exp_val >= 1:
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
