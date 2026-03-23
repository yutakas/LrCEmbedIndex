import logging
import threading
import time

logger = logging.getLogger(__name__)

# Serialize all Ollama API calls (vision + embedding) to avoid
# overloading a local Ollama instance with concurrent requests.
ollama_lock = threading.Lock()

# GPU cooldown: 3-minute break every 57 minutes of Ollama usage.
WORK_DURATION = 57 * 60   # seconds of work before a break
BREAK_DURATION = 3 * 60   # seconds to rest

_work_start = None   # timestamp when the current work window began
_cumulative = 0.0    # seconds of Ollama work accumulated in this window
_cooldown_lock = threading.Lock()


def ollama_cooldown():
    """Call before each Ollama request. Blocks if a cooldown break is due."""
    global _work_start, _cumulative

    with _cooldown_lock:
        now = time.time()

        if _work_start is None:
            _work_start = now
            _cumulative = 0.0
            return

        elapsed = now - _work_start
        if elapsed >= WORK_DURATION:
            remaining_break = BREAK_DURATION - (elapsed - WORK_DURATION)
            if remaining_break > 0:
                logger.info(
                    "GPU cooldown: pausing %.0f seconds (3-min break every hour)",
                    remaining_break,
                )
                # Release lock while sleeping so other threads aren't blocked
                # on the cooldown_lock (they'll wait on ollama_lock anyway).
                _do_sleep(remaining_break)
            # Reset window
            _work_start = time.time()
            _cumulative = 0.0


def _do_sleep(seconds):
    """Sleep outside the lock to allow log reads, but still serialized by ollama_lock."""
    time.sleep(seconds)
