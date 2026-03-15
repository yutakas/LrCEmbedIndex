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


def exif_to_text(exif_data):
    parts = []
    for key, label in EXIF_FIELD_MAP.items():
        val = exif_data.get(key, "")
        if val and str(val).strip():
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


def sanitize_chroma_id(path):
    return path.replace("/", "__").replace("\\", "__").replace(" ", "_")
