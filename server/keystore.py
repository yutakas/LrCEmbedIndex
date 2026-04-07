"""Encrypted storage for API keys using Fernet symmetric encryption.

Generates or loads a machine-specific key from ~/.lrcembedindex_key.
Encrypted values are prefixed with 'ENC:' so they are distinguishable
from plaintext in config files.
"""

import base64
import logging
import os
import stat
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

KEY_FILE = os.path.join(str(Path.home()), ".lrcembedindex_key")

_fernet = None
_fernet_lock = threading.Lock()


def _get_fernet():
    """Return (or create) a Fernet instance backed by the key file."""
    global _fernet
    if _fernet is not None:
        return _fernet

    with _fernet_lock:
        # Double-check after acquiring lock
        if _fernet is not None:
            return _fernet

        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
            logger.debug("Loaded encryption key from %s", KEY_FILE)
        else:
            key = Fernet.generate_key()
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, key)
            finally:
                os.close(fd)
            logger.info("Generated new encryption key at %s", KEY_FILE)

        # Ensure permissions are restrictive (best-effort on non-Unix)
        try:
            os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

        _fernet = Fernet(key)
        return _fernet


def encrypt_value(plaintext):
    """Encrypt a string value. Returns 'ENC:<base64>' string."""
    if not plaintext:
        return ""
    f = _get_fernet()
    token = f.encrypt(plaintext.encode("utf-8"))
    return "ENC:" + token.decode("ascii")


def decrypt_value(ciphertext):
    """Decrypt an 'ENC:...' string. Returns plaintext string.

    If the value is not prefixed with 'ENC:', returns it as-is (backward compat).
    If decryption fails (wrong key), logs a warning and returns empty string.
    """
    if not ciphertext:
        return ""
    if not ciphertext.startswith("ENC:"):
        return ciphertext
    f = _get_fernet()
    try:
        token = ciphertext[4:].encode("ascii")
        return f.decrypt(token).decode("utf-8")
    except (InvalidToken, Exception) as e:
        logger.warning("Failed to decrypt value (wrong key?): %s", e)
        return ""


def is_encrypted(value):
    """Check if a value is an encrypted string."""
    return isinstance(value, str) and value.startswith("ENC:")
