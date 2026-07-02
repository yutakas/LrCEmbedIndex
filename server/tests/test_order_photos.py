"""Tests for photo_utils.order_photos (patrol scan ordering).

Exercises the real function against real files on disk with controlled
modification times. No mocks. Run with: python3 -m pytest server/tests
or standalone: python3 server/tests/test_order_photos.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from photo_utils import order_photos, _file_mtime, SCAN_ORDERS  # noqa: E402


def _make_files(tmp):
    """Create three files and stamp distinct mtimes.

    b.jpg is newest, c.jpg middle, a.jpg oldest -- deliberately NOT matching
    filename order so mtime vs name ordering are distinguishable.
    """
    paths = {}
    for name, mtime in (("a.jpg", 1000), ("b.jpg", 3000), ("c.jpg", 2000)):
        p = os.path.join(tmp, name)
        with open(p, "w") as f:
            f.write("x")
        os.utime(p, (mtime, mtime))
        paths[name] = p
    # Discovery order is filename-sorted, as find_photos would return it.
    return [paths["a.jpg"], paths["b.jpg"], paths["c.jpg"]]


def test_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp)
        result = order_photos(files, "newest")
        assert [os.path.basename(p) for p in result] == ["b.jpg", "c.jpg", "a.jpg"]


def test_oldest_first():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp)
        result = order_photos(files, "oldest")
        assert [os.path.basename(p) for p in result] == ["a.jpg", "c.jpg", "b.jpg"]


def test_name_preserves_discovery_order():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp)
        result = order_photos(files, "name")
        assert result == files


def test_unknown_order_preserves_discovery_order():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp)
        result = order_photos(files, "bogus-value")
        assert result == files


def test_does_not_mutate_input():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp)
        original = list(files)
        order_photos(files, "newest")
        assert files == original


def test_empty_list():
    assert order_photos([], "newest") == []
    assert order_photos([], "name") == []


def test_missing_file_sorts_as_oldest():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp)
        ghost = os.path.join(tmp, "deleted.jpg")  # never created
        # A missing file (mtime 0.0) must sort last under "newest", first
        # under "oldest", and must not raise.
        newest = order_photos(files + [ghost], "newest")
        assert os.path.basename(newest[-1]) == "deleted.jpg"
        oldest = order_photos(files + [ghost], "oldest")
        assert os.path.basename(oldest[0]) == "deleted.jpg"


def test_file_mtime_missing_returns_zero():
    assert _file_mtime("/no/such/path/xyz.jpg") == 0.0


def test_scan_orders_constant():
    assert SCAN_ORDERS == ("newest", "oldest", "name")


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
