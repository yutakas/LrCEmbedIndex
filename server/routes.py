import json
import logging
import subprocess
import tempfile
import threading
import time
import os
import sys
from collections import deque
from functools import wraps
from urllib.parse import unquote

from flask import Blueprint, request, jsonify, send_file, render_template

from config import (config, get_vision_model_label, get_embed_model_label,
                    save_config, save_last_config_pointer, VERSION)
from metadata import (load_photo_metadata, save_photo_metadata,
                      get_vision_result, set_vision_result,
                      get_embed_result, set_embed_result,
                      count_metadata_files, collect_metadata_stats,
                      save_thumbnail, has_thumbnail,
                      thumbnail_path_for_image, metadata_path_for_image,
                      delete_photo_metadata)
from vectorstore import (init_chromadb, upsert_photo, search_photos,
                         get_chromadb_stats, delete_photo)
from vision import describe_image
from embedding import get_embedding
from helpers import exif_to_text, compute_content_hash, resize_thumbnail_bytes

logger = logging.getLogger(__name__)


class LogCapture(logging.Handler):
    """In-memory log handler that stores recent log entries for the web UI."""

    def __init__(self, max_lines=2000):
        super().__init__()
        self.logs = deque(maxlen=max_lines)
        self.setFormatter(logging.Formatter(datefmt="%Y-%m-%d %H:%M:%S"))

    def emit(self, record):
        self.logs.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        })


log_capture = LogCapture()
logging.getLogger().addHandler(log_capture)

api = Blueprint("api", __name__)

# ---------------------------------------------------------------------------
# Patrol interrupt support (must be defined before routes that use them)
# ---------------------------------------------------------------------------

# Module-level reference; set by server.py after patrol worker is created
_patrol_worker = None


def set_patrol_worker(worker):
    """Called by server.py to register the patrol worker for interrupt support."""
    global _patrol_worker
    _patrol_worker = worker


def with_patrol_interrupt(f):
    """Decorator that pauses patrol during Lightroom API calls."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        worker = _patrol_worker
        if worker and worker.is_active():
            worker.interrupt()
        try:
            return f(*args, **kwargs)
        finally:
            if worker:
                worker.clear_interrupt()
    return wrapper


@api.after_request
def add_headers(response):
    """Add CORS and cache-control headers."""
    origin = request.headers.get("Origin", "")
    if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    # Prevent browser from caching JSON API responses
    if response.content_type and "json" in response.content_type:
        response.headers["Cache-Control"] = "no-store"
    return response


@api.route("/", methods=["GET"])
def search_ui():
    """Serve the search web UI."""
    return render_template("search.html")


@api.route("/photo", methods=["GET"])
def photo_detail_ui():
    """Serve the photo detail page."""
    return render_template("photo.html")


@api.route("/collection", methods=["GET"])
def collection_page():
    """Serve a page showing a specific set of photos by path."""
    return render_template("collection.html")


@api.route("/stats-ui", methods=["GET"])
def stats_ui():
    """Serve the stats dashboard page."""
    return render_template("stats.html")


@api.route("/privacy", methods=["GET"])
def privacy_page():
    """Serve the privacy policy page."""
    return render_template("privacy.html")


@api.route("/licenses", methods=["GET"])
def licenses_page():
    """Serve the open source licenses page."""
    return render_template("licenses.html")


@api.route("/settings-ui", methods=["GET"])
def settings_ui():
    """Serve the settings web UI page."""
    return render_template("settings.html")


@api.route("/patrol-ui", methods=["GET"])
def patrol_ui():
    """Serve the patrol status page."""
    return render_template("patrol.html")


@api.route("/logs-ui", methods=["GET"])
def logs_ui():
    """Serve the log viewer page."""
    return render_template("logs.html")


@api.route("/logs", methods=["GET"])
def get_logs():
    """Return captured server logs."""
    limit = request.args.get("limit", 500, type=int)
    logs_list = list(log_capture.logs)[-limit:]
    return jsonify({"status": "ok", "logs": logs_list, "version": VERSION})


@api.route("/logs/clear", methods=["POST"])
def clear_logs():
    """Clear the in-memory log buffer."""
    log_capture.logs.clear()
    return jsonify({"status": "ok"})


@api.route("/settings", methods=["GET"])
def get_settings():
    """Return current config with API keys masked."""
    safe = {}
    for k, v in config.items():
        if "api_key" in k and v:
            safe[k] = "****" + v[-4:] if len(v) > 4 else "****"
        else:
            safe[k] = v
    return jsonify({"status": "ok", "config": safe, "version": VERSION})


@api.route("/settings/sync", methods=["GET"])
def sync_settings():
    """Return full config including API keys (for Lightroom plugin sync).

    This endpoint is localhost-only (enforced by Flask binding to 127.0.0.1).
    """
    return jsonify({"status": "ok", "config": dict(config)})


@api.route("/metadata", methods=["GET"])
def get_metadata():
    """Return the full metadata JSON for an image path."""
    image_path = request.args.get("path", "")
    if not image_path:
        return jsonify({"status": "error", "message": "Missing 'path' parameter"}), 400

    meta = load_photo_metadata(image_path)
    if not meta:
        return jsonify({"status": "error", "message": "No metadata found"}), 404

    # Strip embedding vectors to keep response small
    safe_meta = json.loads(json.dumps(meta))
    for v_label, v_data in safe_meta.get("vision_results", {}).items():
        for e_label, e_data in v_data.get("embeddings", {}).items():
            if "embedding" in e_data:
                e_data["embedding"] = f"[{len(e_data['embedding'])} dimensions]"

    # Compute content hash for display
    try:
        content_hash = compute_content_hash(image_path)
    except (FileNotFoundError, PermissionError):
        content_hash = None

    safe_meta["content_hash"] = content_hash

    return jsonify({"status": "ok", "metadata": safe_meta,
                    "has_thumbnail": has_thumbnail(image_path)})


@api.route("/describe", methods=["POST"])
@with_patrol_interrupt
def describe_photo():
    """Vision-only endpoint: return all cached descriptions, or call API if none exist."""
    t_start = time.time()
    try:
        image_path = request.headers.get("X-Image-Path", "")

        # Parse EXIF
        exif_raw = request.headers.get("X-Exif-Data", "{}")
        exif_json_str = unquote(exif_raw)
        try:
            exif_data = json.loads(exif_json_str)
        except json.JSONDecodeError:
            exif_data = {}

        jpeg_data = request.get_data()
        if not jpeg_data:
            return jsonify({"status": "error", "message": "No image data received"}), 400

        vision_label = get_vision_model_label()

        # Check cached metadata — return ALL cached descriptions if any exist
        existing = load_photo_metadata(image_path) if image_path else None
        vision_results = existing.get("vision_results", {}) if existing else {}

        if vision_results:
            # Build list of all cached descriptions
            descriptions = []
            for model_label, v_data in vision_results.items():
                desc = v_data.get("vision_description")
                if desc:
                    descriptions.append({
                        "vision_model": model_label,
                        "vision_description": desc,
                        "full_description": v_data.get("full_description", desc),
                        "processed_at": v_data.get("processed_at", "unknown"),
                    })

            if descriptions:
                elapsed = time.time() - t_start
                logger.info(f"POST /describe completed in {elapsed:.1f}s — "
                            f"{image_path} ({len(descriptions)} cached model(s))")
                return jsonify({
                    "status": "ok",
                    "descriptions": descriptions,
                    "cached": True,
                    "elapsed": round(elapsed, 2),
                })

        # No cache at all — call vision model with current settings
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(jpeg_data)
                tmp_path = tmp.name

            t_vision = time.time()
            logger.info(f"Describe: generating description for {image_path} using {vision_label}")
            vision_description = describe_image(tmp_path)
            logger.info(f"Describe: vision took {time.time() - t_vision:.1f}s")

            # Append EXIF
            exif_text = exif_to_text(exif_data, strip_gps=config.get("strip_gps_for_cloud", False))
            if exif_text:
                full_description = vision_description + "\n\n--- Photo Metadata ---\n" + exif_text
            else:
                full_description = vision_description

            # Cache the result in metadata
            if image_path:
                meta = existing or {}
                set_vision_result(meta, vision_label, vision_description,
                                  exif_data, full_description)
                save_photo_metadata(image_path, meta)

                # Store thumbnail if configured
                thumb_size = config.get("thumbnail_store_size", 512)
                if thumb_size > 0 and not has_thumbnail(image_path):
                    small_thumb = resize_thumbnail_bytes(jpeg_data, max_size=thumb_size)
                    save_thumbnail(image_path, small_thumb)

            elapsed = time.time() - t_start
            logger.info(f"POST /describe completed in {elapsed:.1f}s — {image_path}")
            return jsonify({
                "status": "ok",
                "descriptions": [{
                    "vision_model": vision_label,
                    "vision_description": vision_description,
                    "full_description": full_description,
                    "processed_at": "just now",
                }],
                "cached": False,
                "elapsed": round(elapsed, 2),
            })

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /describe failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/index", methods=["POST"])
@with_patrol_interrupt
def index_photo():
    t_start = time.time()
    try:
        image_path = request.headers.get("X-Image-Path", "")
        if not image_path:
            return jsonify({"status": "error", "message": "Missing X-Image-Path header"}), 400

        if not config["index_folder"]:
            return jsonify({"status": "error", "message": "Index folder not configured"}), 500

        # Parse EXIF data from header (percent-encoded JSON)
        exif_raw = request.headers.get("X-Exif-Data", "{}")
        exif_json_str = unquote(exif_raw)
        try:
            exif_data = json.loads(exif_json_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse EXIF JSON: {exif_json_str[:200]}")
            exif_data = {}

        # Save incoming JPEG to a temp file
        jpeg_data = request.get_data()
        if not jpeg_data:
            return jsonify({"status": "error", "message": "No image data received"}), 400

        vision_label = get_vision_model_label()
        embed_label = get_embed_model_label()

        # Load existing metadata (may contain results from other models)
        existing = load_photo_metadata(image_path) or {}

        # --- Vision step: reuse if same vision model already ran ---
        cached_vision = get_vision_result(existing, vision_label)
        if cached_vision and cached_vision.get("full_description"):
            description = cached_vision["full_description"]
            vision_description = cached_vision["vision_description"]
            logger.info(f"Reusing cached vision for {image_path} ({vision_label})")
            need_vision = False
        else:
            need_vision = True

        # --- Embed step: reuse cached embedding if vision+embed pair exists ---
        cached_embed = get_embed_result(existing, vision_label, embed_label)
        need_embed = True
        if (not need_vision
                and cached_embed
                and cached_embed.get("embedding")
                and cached_embed.get("description_used") == description):
            # Embedding already computed for this vision+embed pair.
            # Still upsert to ChromaDB since we don't know which model
            # pair produced the current ChromaDB entry.
            embedding = cached_embed["embedding"]
            need_embed = False
            logger.info(f"Reusing cached embedding for {image_path} "
                        f"({vision_label}/{embed_label})")

        # --- Run vision if needed ---
        tmp_path = None
        try:
            if need_vision:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp.write(jpeg_data)
                    tmp_path = tmp.name

                t_vision = time.time()
                logger.info(f"Generating description for {image_path} using {vision_label}")
                vision_description = describe_image(tmp_path)
                logger.info(f"Vision took {time.time() - t_vision:.1f}s — "
                            f"{vision_description[:100]}...")

                # Append EXIF info to description for richer embedding
                exif_text = exif_to_text(exif_data, strip_gps=config.get("strip_gps_for_cloud", False))
                if exif_text:
                    description = vision_description + "\n\n--- Photo Metadata ---\n" + exif_text
                else:
                    description = vision_description

                # Save vision result (preserves other models' results)
                set_vision_result(existing, vision_label, vision_description,
                                  exif_data, description)

            # --- Generate embedding if needed ---
            if need_embed:
                t_embed = time.time()
                logger.info(f"Generating embedding for {image_path} using {embed_label}")
                embedding = get_embedding(description)
                logger.info(f"Embedding took {time.time() - t_embed:.1f}s")
                if not embedding:
                    return jsonify({"status": "error",
                                    "message": "Failed to generate embedding"}), 500

                # Save embed result nested under the vision result
                set_embed_result(existing, vision_label, embed_label,
                                 embedding, description)

            # Persist metadata
            save_photo_metadata(image_path, existing)

            # Store thumbnail if configured
            thumb_size = config.get("thumbnail_store_size", 512)
            if thumb_size > 0 and not has_thumbnail(image_path):
                small_thumb = resize_thumbnail_bytes(jpeg_data, max_size=thumb_size)
                save_thumbnail(image_path, small_thumb)

            # Always upsert to ChromaDB — we don't know which model pair
            # produced the current entry, so keep it in sync.
            # Use client-provided hash when original file is not accessible
            # (e.g. remote Docker server receiving from Lightroom plugin).
            try:
                doc_id = compute_content_hash(image_path)
            except (FileNotFoundError, PermissionError):
                doc_id = request.headers.get("X-Content-Hash", "")
                if not doc_id:
                    return jsonify({"status": "error",
                                    "message": "Original file not accessible and "
                                    "no X-Content-Hash header provided"}), 400
            upsert_photo(doc_id, embedding, description, image_path)
            invalidate_stats_cache()

            elapsed = time.time() - t_start
            skipped_parts = []
            if not need_vision:
                skipped_parts.append("vision")
            if not need_embed:
                skipped_parts.append("embed")
            skip_msg = f" (reused: {', '.join(skipped_parts)})" if skipped_parts else ""
            logger.info(f"POST /index completed in {elapsed:.1f}s — "
                        f"{image_path}{skip_msg}")
            return jsonify({
                "status": "ok",
                "description": description,
                "skipped_vision": not need_vision,
                "skipped_embed": not need_embed,
                "elapsed": round(elapsed, 2),
            })

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /index failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/search", methods=["POST"])
def search_photo():
    t_start = time.time()
    try:
        data = request.get_json()
        if not data or "query" not in data:
            return jsonify({"status": "error", "message": "Missing query"}), 400

        query = data["query"]
        max_results = data.get("max_results", config.get("search_max_results", 10))
        relevance = data.get("relevance", config.get("search_relevance", 50))
        logger.debug(f"Search request: query='{query}', model={get_embed_model_label()}, "
                     f"max_results={max_results}, relevance={relevance}")

        # Get embedding for the search query
        t_embed = time.time()
        embedding = get_embedding(query)
        logger.info(f"Search embedding took {time.time() - t_embed:.1f}s")
        if not embedding:
            return jsonify({"status": "error", "message": "Failed to generate query embedding"}), 500

        matches = search_photos(embedding, n_results=max_results, relevance=relevance)

        elapsed = time.time() - t_start
        logger.info(f"POST /search completed in {elapsed:.1f}s — "
                    f"query='{query}', {len(matches)} results")
        for i, m in enumerate(matches):
            path = os.path.basename(m.get("path", "?"))
            dist = m.get("distance", 0)
            logger.info(f"  #{i+1} dist={dist:.4f}  {path}")
        return jsonify({"status": "ok", "results": matches, "elapsed": round(elapsed, 2)})

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /search failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/settings", methods=["POST"])
def update_settings():
    t_start = time.time()
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        folder_changed = False
        if "index_folder" in data and data["index_folder"] != config["index_folder"]:
            config["index_folder"] = data["index_folder"]
            folder_changed = True

        # Vision settings
        for key in ("vision_mode", "ollama_vision_endpoint", "ollama_vision_model",
                     "openai_vision_api_key", "openai_vision_model",
                     "claude_vision_api_key", "claude_vision_model"):
            if key in data:
                config[key] = data[key]

        # Embedding settings
        for key in ("embed_mode", "ollama_embed_endpoint", "ollama_embed_model",
                     "openai_embed_api_key", "openai_embed_model",
                     "voyage_embed_api_key", "voyage_embed_model"):
            if key in data:
                config[key] = data[key]

        # Search settings
        if "search_max_results" in data:
            config["search_max_results"] = max(1, int(data["search_max_results"]))
        if "search_relevance" in data:
            config["search_relevance"] = max(0, min(100, int(data["search_relevance"])))

        # Thumbnail settings
        if "thumbnail_store_size" in data:
            config["thumbnail_store_size"] = max(0, int(data["thumbnail_store_size"]))

        # Privacy settings
        if "strip_gps_for_cloud" in data:
            config["strip_gps_for_cloud"] = bool(data["strip_gps_for_cloud"])

        # Debug settings
        if "debug_logging" in data:
            config["debug_logging"] = bool(data["debug_logging"])
            root = logging.getLogger()
            root.setLevel(logging.DEBUG if config["debug_logging"] else logging.INFO)
            logger.info(f"Debug logging {'enabled' if config['debug_logging'] else 'disabled'}")

        # Patrol settings
        if "patrol_enabled" in data:
            config["patrol_enabled"] = bool(data["patrol_enabled"])
        if "patrol_folders" in data:
            config["patrol_folders"] = data["patrol_folders"]
        if "patrol_interval_minutes" in data:
            config["patrol_interval_minutes"] = max(1, int(data["patrol_interval_minutes"]))
        if "patrol_batch_size" in data:
            config["patrol_batch_size"] = max(1, int(data["patrol_batch_size"]))
        for key in ("patrol_start_time", "patrol_end_time"):
            if key in data:
                val = (data[key] or "").strip()
                if val:
                    try:
                        parts = val.split(":")
                        h, m = int(parts[0]), int(parts[1])
                        if not (0 <= h <= 23 and 0 <= m <= 59):
                            raise ValueError
                        val = f"{h:02d}:{m:02d}"
                    except (ValueError, IndexError, AttributeError):
                        return jsonify({"status": "error",
                                        "message": f"Invalid time format for {key}: '{data[key]}'"}), 400
                config[key] = val

        save_config()
        save_last_config_pointer()

        if folder_changed:
            init_chromadb()

        elapsed = time.time() - t_start
        logger.info(f"POST /settings completed in {elapsed:.1f}s — "
                    f"vision={get_vision_model_label()}, "
                    f"embed={get_embed_model_label()}, "
                    f"folder={config['index_folder']}")
        return jsonify({"status": "ok", "config": {
            k: v for k, v in config.items() if "api_key" not in k
        }})

    except Exception as e:
        elapsed = time.time() - t_start
        logger.exception(f"POST /settings failed in {elapsed:.1f}s: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


_stats_cache = None
_stats_cache_time = 0
_stats_computing = False
_stats_lock = threading.Lock()
_STATS_CACHE_TTL = 300  # seconds


def invalidate_stats_cache():
    """Call after indexing or deleting photos to force a fresh stats computation."""
    global _stats_cache_time
    _stats_cache_time = 0
    _trigger_stats_refresh()


def _compute_stats_background():
    """Compute stats in a background thread and update the cache."""
    global _stats_cache, _stats_cache_time, _stats_computing
    try:
        t_start = time.time()

        meta_count = count_metadata_files()
        meta_stats = collect_metadata_stats()
        chroma_stats = get_chromadb_stats()
        safe_config = {k: v for k, v in config.items() if "api_key" not in k}

        elapsed = time.time() - t_start
        logger.info(f"Stats computed in {elapsed:.1f}s")
        result = {
            "status": "ok",
            "metadata": {
                "total_files": meta_count,
                "thumbnail_files": meta_stats.get("thumbnail_count", 0),
                "vision_models": meta_stats.get("vision_models", {}),
                "embed_models": meta_stats.get("embed_models", {}),
                "oldest_entry": meta_stats.get("oldest_entry"),
                "newest_entry": meta_stats.get("newest_entry"),
            },
            "chromadb": chroma_stats,
            "config": safe_config,
            "version": VERSION,
            "elapsed": round(elapsed, 2),
            "cached": False,
        }
        _stats_cache = result
        _stats_cache_time = time.time()
    except Exception:
        logger.exception("Background stats computation failed")
    finally:
        with _stats_lock:
            _stats_computing = False


def _trigger_stats_refresh():
    """Kick off a background stats computation if one isn't already running."""
    global _stats_computing
    with _stats_lock:
        if _stats_computing:
            return
        _stats_computing = True
    threading.Thread(target=_compute_stats_background, daemon=True).start()


def compute_stats_cached():
    """Return stats dict, using a background-refreshed cache.

    Never blocks for a full stats computation. If the cache is stale or empty,
    triggers a background refresh and returns whatever is available (stale cache
    or a placeholder).

    Shared by the /stats HTTP endpoint and the MCP get_stats tool.
    """
    now = time.time()
    stale = (now - _stats_cache_time) >= _STATS_CACHE_TTL

    if stale:
        _trigger_stats_refresh()

    if _stats_cache:
        cached = dict(_stats_cache)
        cached["config"] = {k: v for k, v in config.items() if "api_key" not in k}
        cached["cached"] = True
        cached["computing"] = _stats_computing
        return cached

    # No cache at all yet (first request after startup)
    return {
        "status": "ok",
        "metadata": {"total_files": 0, "thumbnail_files": 0,
                      "vision_models": {}, "embed_models": {},
                      "oldest_entry": None, "newest_entry": None},
        "chromadb": {"current_model": "", "current_count": 0,
                     "current_path": "", "all_stores": []},
        "config": {k: v for k, v in config.items() if "api_key" not in k},
        "version": VERSION,
        "elapsed": 0,
        "cached": False,
        "computing": True,
    }


@api.route("/stats", methods=["GET"])
def get_stats():
    try:
        return jsonify(compute_stats_cached())
    except Exception as e:
        logger.exception(f"GET /stats failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/thumbnail", methods=["GET"])
def get_thumbnail():
    """Return the stored thumbnail JPEG for an image path."""
    image_path = request.args.get("path", "")
    if not image_path:
        return jsonify({"status": "error", "message": "Missing 'path' parameter"}), 400

    thumb_path = thumbnail_path_for_image(image_path)
    if not thumb_path or not os.path.exists(thumb_path):
        return jsonify({"status": "error", "message": "No thumbnail found"}), 404

    return send_file(thumb_path, mimetype="image/jpeg")


KNOWN_PHOTO_APPS = [
    ("Adobe Lightroom Classic", "/Applications/Adobe Lightroom Classic/Adobe Lightroom Classic.app"),
    ("Adobe Photoshop", "/Applications/Adobe Photoshop 2025/Adobe Photoshop 2025.app"),
    ("Adobe Photoshop", "/Applications/Adobe Photoshop 2024/Adobe Photoshop 2024.app"),
    ("Adobe Bridge", "/Applications/Adobe Bridge 2025/Adobe Bridge 2025.app"),
    ("Adobe Bridge", "/Applications/Adobe Bridge 2024/Adobe Bridge 2024.app"),
    ("Affinity Photo 2", "/Applications/Affinity Photo 2.app"),
    ("Capture One", "/Applications/Capture One.app"),
    ("DxO PhotoLab", "/Applications/DxO PhotoLab 8.app"),
    ("DxO PhotoLab", "/Applications/DxO PhotoLab 7.app"),
    ("Photos", "/Applications/Photos.app"),
    ("Preview", "/Applications/Preview.app"),
]


@api.route("/apps", methods=["GET"])
def list_apps():
    """Return a list of installed photo applications."""
    installed = []
    seen = set()
    if sys.platform == "darwin":
        for name, path in KNOWN_PHOTO_APPS:
            if name not in seen and os.path.exists(path):
                installed.append({"name": name, "path": path})
                seen.add(name)
    return jsonify({"status": "ok", "apps": installed})


def _is_indexed_path(file_path):
    """Check if a file path exists in the metadata index."""
    meta_path = metadata_path_for_image(file_path)
    return meta_path is not None and os.path.exists(meta_path)


def _is_known_app(app_path):
    """Check if an app path is in the known photo apps list."""
    return any(path == app_path for _, path in KNOWN_PHOTO_APPS)


@api.route("/open", methods=["POST"])
def open_file():
    """Open or reveal a photo file on the local machine."""
    data = request.get_json()
    if not data or "path" not in data:
        return jsonify({"status": "error", "message": "Missing 'path'"}), 400

    file_path = os.path.abspath(data["path"])
    action = data.get("action", "open")
    app_path = data.get("app")

    # Only allow opening files that are in the metadata index
    if not _is_indexed_path(data["path"]):
        return jsonify({"status": "error",
                        "message": "Path not in index"}), 403

    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "File not found"}), 404

    # Only allow known photo apps
    if app_path and not _is_known_app(app_path):
        return jsonify({"status": "error",
                        "message": "Unknown application"}), 403

    try:
        if sys.platform == "darwin":
            if action == "reveal":
                subprocess.Popen(["open", "-R", file_path])
            elif app_path:
                subprocess.Popen(["open", "-a", app_path, file_path])
            else:
                subprocess.Popen(["open", file_path])
        elif sys.platform == "win32":
            if action == "reveal":
                subprocess.Popen(["explorer", "/select,", file_path])
            else:
                os.startfile(file_path)
        else:
            subprocess.Popen(["xdg-open", file_path])

        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route("/metadata", methods=["DELETE"])
def delete_metadata():
    """Delete all indexed data (metadata, thumbnail, ChromaDB entry) for a photo."""
    image_path = request.args.get("path", "")
    if not image_path:
        return jsonify({"status": "error", "message": "Missing 'path' parameter"}), 400

    # Try to compute content hash for ChromaDB deletion
    try:
        doc_id = compute_content_hash(image_path)
        delete_photo(doc_id)
    except (FileNotFoundError, PermissionError):
        pass  # original file may be gone, still delete metadata

    deleted = delete_photo_metadata(image_path)
    if not deleted:
        return jsonify({"status": "error", "message": "No metadata found"}), 404

    invalidate_stats_cache()
    return jsonify({"status": "ok", "message": "Photo data deleted"})


# ---------------------------------------------------------------------------
# Patrol control endpoints
# ---------------------------------------------------------------------------

@api.route("/patrol/status", methods=["GET"])
def patrol_status():
    """Return current patrol worker state."""
    worker = _patrol_worker
    if not worker:
        return jsonify({"status": "ok", "patrol": {"state": "not_initialized"}})
    return jsonify({"status": "ok", "patrol": worker.get_status()})


@api.route("/patrol/start", methods=["POST"])
def patrol_start():
    """Start or resume the patrol worker."""
    worker = _patrol_worker
    if not worker:
        return jsonify({"status": "error", "message": "Patrol worker not initialized"}), 500
    config["patrol_enabled"] = True
    save_config()
    save_last_config_pointer()
    worker.start(force=True)
    return jsonify({"status": "ok", "patrol": worker.get_status()})


@api.route("/patrol/pause", methods=["POST"])
def patrol_pause():
    """Pause the patrol worker (finishes current photo first)."""
    worker = _patrol_worker
    if not worker:
        return jsonify({"status": "error", "message": "Patrol worker not initialized"}), 500
    worker.pause()
    return jsonify({"status": "ok", "patrol": worker.get_status()})


@api.route("/patrol/stop", methods=["POST"])
def patrol_stop():
    """Stop the patrol worker."""
    worker = _patrol_worker
    if not worker:
        return jsonify({"status": "error", "message": "Patrol worker not initialized"}), 500
    config["patrol_enabled"] = False
    save_config()
    save_last_config_pointer()
    worker.stop()
    return jsonify({"status": "ok", "patrol": worker.get_status()})
