"""Background patrol worker that auto-discovers and indexes photos from watched folders.

Uses polling-based scanning on a configurable interval. Processes photos in
batches with cooperative interruption support for Lightroom requests.
"""

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

from config import config, get_vision_model_label, get_embed_model_label
from metadata import (
    load_photo_metadata, save_photo_metadata, metadata_path_for_image,
    get_vision_result, set_vision_result,
    get_embed_result, set_embed_result,
    has_thumbnail, save_thumbnail,
)
from vectorstore import upsert_photo
from vision import describe_image
from embedding import get_embedding
from helpers import exif_to_text, compute_content_hash, resize_thumbnail_bytes
from photo_utils import find_photos, make_thumbnail, extract_exif, extract_exif_raw, RAW_EXTENSIONS

logger = logging.getLogger(__name__)

STATE_FILENAME = "patrol_state.json"


class PatrolWorker:
    """Background thread that periodically scans folders and indexes new photos."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._interrupt_event = threading.Event()
        self._pause_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()
        self._force_scan = False

        # Status tracking
        self._state = "idle"       # idle, scanning, waiting, paused, stopped
        self._files_processed = 0
        self._files_remaining = 0
        self._current_file = ""
        self._last_scan_time = None
        self._errors = 0

        # Timing tracking
        self._scan_start_time = None
        self._scan_elapsed = None        # seconds for last completed scan
        self._current_file_start = None
        self._current_vision_time = None
        self._current_embed_time = None
        self._total_discovered = 0
        self._recent_files = []          # list of recent file dicts (max 50)

    def start(self, force=False):
        """Start (or resume) the patrol worker thread.

        Args:
            force: If True, run a scan immediately regardless of the time window.
        """
        with self._lock:
            if self._thread and self._thread.is_alive():
                # Resume if paused
                if self._state == "paused":
                    self._pause_event.clear()
                    self._state = "idle"
                    logger.info("Patrol resumed")
                if force:
                    self._force_scan = True
                    self._wake_event.set()
                return

            self._stop_event.clear()
            self._pause_event.clear()
            self._interrupt_event.clear()
            self._force_scan = force
            self._state = "idle"
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            logger.info("Patrol worker started")

    def stop(self):
        """Stop the patrol worker thread."""
        with self._lock:
            self._stop_event.set()
            self._wake_event.set()
            self._pause_event.clear()
            self._state = "stopped"
            logger.info("Patrol worker stopping")

    def pause(self):
        """Pause the patrol worker (finishes current photo first)."""
        with self._lock:
            self._pause_event.set()
            self._state = "paused"
            logger.info("Patrol worker paused")

    def interrupt(self):
        """Signal the patrol to yield for a Lightroom request."""
        self._interrupt_event.set()
        # Wait briefly for patrol to acknowledge
        for _ in range(20):
            if self._state != "scanning":
                break
            time.sleep(0.1)

    def clear_interrupt(self):
        """Clear the interrupt flag so patrol can resume."""
        self._interrupt_event.clear()

    def is_active(self):
        """Return True if the patrol is actively scanning."""
        return self._state == "scanning"

    def get_status(self):
        """Return current status dict for the API."""
        status = {
            "state": self._state,
            "running": self._thread is not None and self._thread.is_alive(),
            "files_processed": self._files_processed,
            "files_remaining": self._files_remaining,
            "current_file": self._current_file,
            "last_scan_time": self._last_scan_time,
            "errors": self._errors,
            "total_discovered": self._total_discovered,
            "scan_start_time": self._scan_start_time,
            "scan_elapsed": self._scan_elapsed,
            "current_file_start": self._current_file_start,
            "current_vision_time": self._current_vision_time,
            "current_embed_time": self._current_embed_time,
            "recent_files": list(self._recent_files),
        }
        if self._state == "waiting":
            start_str = config.get("patrol_start_time", "")
            end_str = config.get("patrol_end_time", "")
            if start_str and end_str:
                status["waiting_reason"] = f"outside active hours {start_str}\u2013{end_str}"
        return status

    def _run(self):
        """Main patrol loop — scan, sleep, repeat."""
        logger.info("Patrol loop started")
        first_run = True
        while not self._stop_event.is_set():
            if first_run:
                first_run = False
            else:
                # Show correct state while sleeping
                if not self._is_within_time_window():
                    self._state = "waiting"
                else:
                    self._state = "idle"
                # Wait for the configured interval, but wake on stop or force_scan
                interval = config.get("patrol_interval_minutes", 5) * 60
                self._wake_event.clear()
                self._wake_event.wait(timeout=interval)
                if self._stop_event.is_set():
                    break

            if self._pause_event.is_set():
                continue

            # Check time window — bypass if manually forced
            force = self._force_scan
            if force:
                self._force_scan = False
                logger.info("Patrol: forced scan requested, bypassing time window")
            elif not self._is_within_time_window():
                self._state = "waiting"
                continue

            self._do_scan()

        self._state = "stopped"
        logger.info("Patrol loop stopped")

    def _is_within_time_window(self):
        """Check if the current local time is within the configured patrol window.

        Returns True if no window is configured (both fields empty) or if the
        current time falls inside the start–end range.  Supports overnight
        windows (e.g. start=22:00 end=06:00).
        """
        start_str = config.get("patrol_start_time", "").strip()
        end_str = config.get("patrol_end_time", "").strip()
        if not start_str or not end_str:
            return True

        try:
            sp = start_str.split(":")
            ep = end_str.split(":")
            sh, sm = int(sp[0]), int(sp[1])
            eh, em = int(ep[0]), int(ep[1])
            if not (0 <= sh <= 23 and 0 <= sm <= 59
                    and 0 <= eh <= 23 and 0 <= em <= 59):
                raise ValueError
        except (ValueError, IndexError, AttributeError):
            logger.warning(f"Patrol: invalid time window '{start_str}'-'{end_str}', ignoring")
            return True

        now = datetime.now()
        cur = now.hour * 60 + now.minute
        start = sh * 60 + sm
        end = eh * 60 + em

        if start <= end:
            # Same-day window, e.g. 08:00–18:00
            inside = start <= cur < end
        else:
            # Overnight window, e.g. 22:00–06:00
            inside = cur >= start or cur < end

        tz_name = now.astimezone().tzinfo
        if inside:
            logger.debug(f"Patrol: inside time window {start_str}-{end_str} "
                         f"(now {now.strftime('%H:%M')}, tz={tz_name})")
        else:
            logger.debug(f"Patrol: outside time window {start_str}-{end_str} "
                         f"(now {now.strftime('%H:%M')}, tz={tz_name}), skipping scan")
        return inside

    def _do_scan(self):
        """Scan all configured folders and index new/changed photos."""
        folders = config.get("patrol_folders", [])
        if not folders:
            return

        if not config.get("index_folder"):
            logger.warning("Patrol: index_folder not configured, skipping scan")
            return

        self._state = "scanning"
        self._files_processed = 0
        self._errors = 0
        self._scan_start_time = datetime.now(timezone.utc).isoformat()
        self._scan_elapsed = None
        scan_t0 = time.time()

        # Discover all photos across all watched folders
        all_photos = []
        for folder_entry in folders:
            if isinstance(folder_entry, str):
                folder_path = folder_entry
                recursive = True
            else:
                folder_path = folder_entry.get("path", "")
                recursive = folder_entry.get("recursive", True)

            if not folder_path or not os.path.isdir(folder_path):
                logger.warning(f"Patrol: skipping invalid folder: {folder_path}")
                continue

            if recursive:
                photos = find_photos(folder_path)
            else:
                # Non-recursive: only top-level files
                from photo_utils import DEFAULT_EXTENSIONS
                photos = []
                for fname in sorted(os.listdir(folder_path)):
                    if os.path.splitext(fname)[1].lower() in DEFAULT_EXTENSIONS:
                        full = os.path.join(folder_path, fname)
                        if os.path.isfile(full):
                            photos.append(full)
            all_photos.extend(photos)

        # Filter to only unindexed or changed photos
        to_index = []
        for photo_path in all_photos:
            if self._should_index(photo_path):
                to_index.append(photo_path)

        self._files_remaining = len(to_index)
        self._total_discovered = len(all_photos)
        logger.info(f"Patrol: found {len(all_photos)} photos, {len(to_index)} need indexing")

        if not to_index:
            self._state = "idle"
            self._last_scan_time = datetime.now(timezone.utc).isoformat()
            self._save_state()
            return

        # Process in batches
        for i, photo_path in enumerate(to_index):
            # Check for stop/pause/interrupt/time-window between photos
            if self._stop_event.is_set():
                break
            if self._pause_event.is_set():
                self._state = "paused"
                break
            if not self._force_scan and not self._is_within_time_window():
                logger.info("Patrol: time window closed, stopping scan "
                            f"({self._files_processed} done, {len(to_index) - i} remaining)")
                self._state = "waiting"
                break
            if self._interrupt_event.is_set():
                self._state = "interrupted"
                # Wait for interrupt to clear
                while self._interrupt_event.is_set() and not self._stop_event.is_set():
                    time.sleep(0.2)
                if self._stop_event.is_set():
                    break
                self._state = "scanning"

            self._current_file = photo_path
            self._current_file_start = time.time()
            self._current_vision_time = None
            self._current_embed_time = None
            self._files_remaining = len(to_index) - i

            try:
                self._index_photo(photo_path)
                self._files_processed += 1
                elapsed = time.time() - self._current_file_start
                self._recent_files.append({
                    "file": os.path.basename(photo_path),
                    "path": photo_path,
                    "status": "ok",
                    "total_time": round(elapsed, 1),
                    "vision_time": self._current_vision_time,
                    "embed_time": self._current_embed_time,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.warning(f"Patrol: failed to index {photo_path}: {e}")
                self._errors += 1
                elapsed = time.time() - self._current_file_start
                self._recent_files.append({
                    "file": os.path.basename(photo_path),
                    "path": photo_path,
                    "status": "error",
                    "error": str(e),
                    "total_time": round(elapsed, 1),
                    "vision_time": self._current_vision_time,
                    "embed_time": self._current_embed_time,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            # Keep only the last 50 entries
            if len(self._recent_files) > 50:
                self._recent_files = self._recent_files[-50:]

        self._current_file = ""
        self._current_file_start = None
        self._last_scan_time = datetime.now(timezone.utc).isoformat()
        self._scan_elapsed = round(time.time() - scan_t0, 1)
        if self._state == "scanning":
            self._state = "idle"
        self._save_state()
        logger.info(f"Patrol scan complete: {self._files_processed} indexed, "
                    f"{self._errors} errors")

    def _should_index(self, image_path):
        """Check if a photo needs indexing (not yet indexed or file changed)."""
        meta_path = metadata_path_for_image(image_path)
        if meta_path is None:
            return True
        if not os.path.exists(meta_path):
            return True

        # Check if file was modified after metadata was created
        try:
            file_mtime = os.path.getmtime(image_path)
            meta_mtime = os.path.getmtime(meta_path)
            if file_mtime > meta_mtime:
                return True
        except OSError:
            return True

        return False

    def _index_photo(self, image_path):
        """Index a single photo (vision + embedding + metadata + ChromaDB)."""
        vision_label = get_vision_model_label()
        embed_label = get_embed_model_label()

        basename = os.path.basename(image_path)
        logger.info(f"Patrol indexing: {basename}")

        # Generate thumbnail (skip photo if RAW format is unsupported, e.g. Nikon Z9 compressed)
        try:
            jpeg_data = make_thumbnail(image_path)
        except Exception as e:
            logger.warning(f"Patrol: thumbnail failed for {basename}, skipping: {e}")
            return

        # Extract EXIF
        ext = os.path.splitext(image_path)[1].lower()
        if ext in RAW_EXTENSIONS:
            exif_data = extract_exif_raw(image_path)
        else:
            exif_data = extract_exif(image_path)

        # Load existing metadata
        existing = load_photo_metadata(image_path) or {}

        # Vision step: reuse if same vision model already ran
        cached_vision = get_vision_result(existing, vision_label)
        if cached_vision and cached_vision.get("full_description"):
            description = cached_vision["full_description"]
            vision_description = cached_vision["vision_description"]
            need_vision = False
        else:
            need_vision = True

        # Embed step: reuse if vision+embed pair exists
        cached_embed = get_embed_result(existing, vision_label, embed_label)
        need_embed = True
        if (not need_vision
                and cached_embed
                and cached_embed.get("embedding")
                and cached_embed.get("description_used") == description):
            embedding = cached_embed["embedding"]
            need_embed = False

        # Run vision if needed
        tmp_path = None
        try:
            if need_vision:
                # Check for interrupt before expensive vision call
                if self._interrupt_event.is_set():
                    return

                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp.write(jpeg_data)
                    tmp_path = tmp.name

                t_vision = time.time()
                vision_description = describe_image(tmp_path)
                self._current_vision_time = round(time.time() - t_vision, 1)
                logger.info(f"Patrol vision took {self._current_vision_time}s for {basename}")

                exif_text = exif_to_text(exif_data,
                                        strip_gps=config.get("strip_gps_for_cloud", False))
                if exif_text:
                    description = vision_description + "\n\n--- Photo Metadata ---\n" + exif_text
                else:
                    description = vision_description

                set_vision_result(existing, vision_label, vision_description,
                                  exif_data, description)

            # Check for interrupt before embedding call
            if self._interrupt_event.is_set():
                # Save what we have so far
                save_photo_metadata(image_path, existing)
                return

            if need_embed:
                t_embed = time.time()
                embedding = get_embedding(description)
                self._current_embed_time = round(time.time() - t_embed, 1)
                logger.info(f"Patrol embedding took {self._current_embed_time}s for {basename}")
                if not embedding:
                    logger.warning(f"Patrol: empty embedding for {basename}")
                    return

                set_embed_result(existing, vision_label, embed_label,
                                 embedding, description)

            # Save metadata
            save_photo_metadata(image_path, existing)

            # Store thumbnail if configured
            thumb_size = config.get("thumbnail_store_size", 512)
            if thumb_size > 0 and not has_thumbnail(image_path):
                small_thumb = resize_thumbnail_bytes(jpeg_data, max_size=thumb_size)
                save_thumbnail(image_path, small_thumb)

            # Upsert to ChromaDB
            try:
                doc_id = compute_content_hash(image_path)
            except (FileNotFoundError, PermissionError) as e:
                logger.warning(f"Patrol: cannot hash {image_path}: {e}")
                return
            upsert_photo(doc_id, embedding, description, image_path)

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _save_state(self):
        """Persist patrol state for resumability across restarts."""
        if not config.get("index_folder"):
            return
        state_path = os.path.join(config["index_folder"], STATE_FILENAME)
        state = {
            "last_scan_time": self._last_scan_time,
            "files_processed": self._files_processed,
            "errors": self._errors,
        }
        try:
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save patrol state: {e}")
