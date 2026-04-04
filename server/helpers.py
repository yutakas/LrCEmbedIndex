EXIF_FIELD_MAP = {
    "cameraMake": "Camera Make",
    "cameraModel": "Camera Model",
    "lens": "Lens",
    "focalLength": "Focal Length",
    "aperture": "Aperture",
    "shutterSpeed": "Shutter Speed",
    "isoSpeedRating": "ISO",
    "exposureBias": "Exposure Bias",
    "dateTimeOriginal": "Date Taken",
    "gps": "GPS Location",
    "fileName": "File Name",
    "fileType": "File Type",
    "dimensions": "Dimensions",
    "title": "Title",
    "caption": "Caption",
    "keywords": "Keywords",
    "label": "Label",
    "rating": "Rating",
}


def exif_to_text(exif_data, strip_gps=False):
    parts = []
    for key, label in EXIF_FIELD_MAP.items():
        if strip_gps and key == "gps":
            continue
        val = exif_data.get(key, "")
        if val and str(val).strip():
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


def sanitize_chroma_id(path):
    return path.replace("/", "__").replace("\\", "__").replace(" ", "_")


def resize_thumbnail_bytes(jpeg_bytes, max_size=512, quality=85):
    """Downscale JPEG bytes to fit within max_size. Returns JPEG bytes."""
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(jpeg_bytes))
    if max(img.size) <= max_size:
        return jpeg_bytes
    img.thumbnail((max_size, max_size))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def compute_content_hash(file_path, chunk_size=65536):
    """Compute SHA-256 hash of file content, returned as 'sha256:<hex>'."""
    import hashlib

    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"
