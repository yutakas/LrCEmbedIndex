"""Tests for photo_utils thumbnail generation, including the embedded-preview
fallback for RAW formats LibRaw cannot decode (e.g. Nikon Z8/Z9 HE* NEF).

Pillow code paths run against real image files generated on disk. The RAW
fallback logic is exercised with a stub rawpy module injected into
sys.modules -- a real HE* NEF cannot be committed to the repo (file size,
copyright) and rawpy is not installed in every dev environment. Set
LRCEI_TEST_RAW_FILE=/path/to/file.nef to additionally run the real
end-to-end fallback against an actual RAW file with the real rawpy.

Run with: python3 -m pytest server/tests
or standalone: python3 server/tests/test_make_thumbnail.py
"""

import io
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import photo_utils  # noqa: E402
from photo_utils import (  # noqa: E402
    make_thumbnail, make_thumbnail_pillow, MAX_THUMB_SIZE,
)

from PIL import Image  # noqa: E402


def _write_image(path, size=(2000, 1500), mode="RGB", fmt=None):
    Image.new(mode, size, color=(200, 120, 40) if mode == "RGB" else None).save(
        path, format=fmt)
    return path


def _assert_valid_jpeg(data, max_size):
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG"
    assert max(img.size) <= max_size
    return img


# ---------------------------------------------------------------------------
# Pillow path (real files, no stubs)
# ---------------------------------------------------------------------------

def test_jpeg_thumbnail_resizes_to_default_max():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_image(os.path.join(tmp, "photo.jpg"))
        data = make_thumbnail(p)
        img = _assert_valid_jpeg(data, MAX_THUMB_SIZE)
        # 2000x1500 shrinks to exactly 1024 on the long edge
        assert max(img.size) == MAX_THUMB_SIZE


def test_custom_max_size_and_small_image_not_upscaled():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_image(os.path.join(tmp, "photo.jpg"))
        data = make_thumbnail(p, max_size=512)
        _assert_valid_jpeg(data, 512)

        small = _write_image(os.path.join(tmp, "small.jpg"), size=(100, 80))
        data = make_thumbnail(small)
        img = Image.open(io.BytesIO(data))
        assert img.size == (100, 80)


def test_rgba_png_converted_to_rgb():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "photo.png")
        Image.new("RGBA", (300, 200), (10, 20, 30, 128)).save(p)
        data = make_thumbnail(p)
        img = _assert_valid_jpeg(data, MAX_THUMB_SIZE)
        assert img.mode == "RGB"


def test_dispatch_uses_pillow_for_non_raw():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_image(os.path.join(tmp, "photo.jpg"))
        assert make_thumbnail(p) == make_thumbnail_pillow(p)


def test_generate_thumbnails_uses_shared_impl():
    import generate_thumbnails
    assert generate_thumbnails.make_thumbnail is photo_utils.make_thumbnail


# ---------------------------------------------------------------------------
# RAW fallback path (stub rawpy -- see module docstring for why)
# ---------------------------------------------------------------------------

def _make_stub_rawpy(thumb_format=None, thumb_data=None):
    """Build a minimal rawpy stand-in whose postprocess always fails with
    LibRawError (simulating an HE* NEF) and whose extract_thumb returns the
    given preview."""
    mod = types.ModuleType("rawpy")

    class LibRawError(Exception):
        pass

    class ThumbFormat:
        JPEG = "jpeg"
        BITMAP = "bitmap"

    class _Raw:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def postprocess(self, **kwargs):
            raise LibRawError("Unsupported file format or not RAW file")

        def extract_thumb(self):
            return types.SimpleNamespace(format=thumb_format, data=thumb_data)

    mod.LibRawError = LibRawError
    mod.ThumbFormat = ThumbFormat
    mod.imread = lambda path: _Raw()
    return mod


def _with_stub_rawpy(stub, fn):
    saved = sys.modules.get("rawpy")
    sys.modules["rawpy"] = stub
    try:
        return fn()
    finally:
        if saved is None:
            del sys.modules["rawpy"]
        else:
            sys.modules["rawpy"] = saved


def _jpeg_bytes(size=(3000, 2000)):
    buf = io.BytesIO()
    Image.new("RGB", size, (90, 140, 60)).save(buf, format="JPEG")
    return buf.getvalue()


def test_raw_fallback_to_embedded_jpeg_preview():
    """postprocess raising LibRawError must fall back to the embedded JPEG."""
    stub = _make_stub_rawpy(thumb_format="jpeg", thumb_data=_jpeg_bytes())

    def run():
        data = make_thumbnail("/nonexistent/fake.nef")
        img = _assert_valid_jpeg(data, MAX_THUMB_SIZE)
        assert max(img.size) == MAX_THUMB_SIZE

    _with_stub_rawpy(stub, run)


def test_raw_fallback_to_bitmap_preview():
    """A BITMAP-format preview must be converted via Image.fromarray."""
    try:
        import numpy as np
    except ImportError:
        return  # numpy not available; production always has it via chromadb
    arr = np.zeros((200, 300, 3), dtype=np.uint8)
    stub = _make_stub_rawpy(thumb_format="bitmap", thumb_data=arr)

    def run():
        data = make_thumbnail("/nonexistent/fake.nef")
        img = Image.open(io.BytesIO(data))
        assert img.size == (300, 200)

    _with_stub_rawpy(stub, run)


def test_raw_non_libraw_errors_still_propagate():
    """Only LibRaw decode errors trigger the fallback; e.g. a missing file
    (OSError from the stub's imread) must still raise so callers skip it."""
    stub = _make_stub_rawpy()

    def imread(path):
        raise OSError("no such file")

    stub.imread = imread

    def run():
        try:
            make_thumbnail("/nonexistent/fake.nef")
        except OSError:
            return
        raise AssertionError("expected OSError to propagate")

    _with_stub_rawpy(stub, run)


# ---------------------------------------------------------------------------
# Optional real-file integration test (real rawpy, real RAW file)
# ---------------------------------------------------------------------------

def test_real_raw_file_if_configured():
    """End-to-end with the real rawpy against a real RAW file.

    Skipped unless LRCEI_TEST_RAW_FILE points at an existing RAW file.
    Use a Nikon Z8/Z9 High Efficiency NEF to exercise the fallback path.
    """
    path = os.environ.get("LRCEI_TEST_RAW_FILE")
    if not path or not os.path.exists(path):
        return
    data = make_thumbnail(path)
    img = _assert_valid_jpeg(data, MAX_THUMB_SIZE)
    assert min(img.size) > 0
    print(f"  real RAW thumbnail: {img.size}, {len(data)} bytes")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
