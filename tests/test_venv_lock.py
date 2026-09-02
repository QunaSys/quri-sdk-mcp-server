"""Self-check for the persistent venv cache's lock and freshness-marker logic.

Run directly: `python tests/test_venv_lock.py`.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from quri_sdk_mcp.py_checker.pyright_check import (
    _is_venv_fresh,
    _prune_stale_venvs,
    _try_venv_lock,
    _venv_lock,
)


def test_lock_excludes_concurrent_entry():
    with tempfile.TemporaryDirectory() as cache_root:
        cache_root = Path(cache_root)
        concurrent = {"count": 0, "max": 0}
        guard = threading.Lock()

        def worker():
            with _venv_lock(cache_root, "key"):
                with guard:
                    concurrent["count"] += 1
                    concurrent["max"] = max(concurrent["max"], concurrent["count"])
                time.sleep(0.05)
                with guard:
                    concurrent["count"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert concurrent["max"] == 1


def test_held_lock_blocks_try_lock():
    with tempfile.TemporaryDirectory() as cache_root:
        cache_root = Path(cache_root)
        with _venv_lock(cache_root, "key"):
            try:
                with _try_venv_lock(cache_root, "key"):
                    raise AssertionError("should not have acquired a held lock")
            except OSError:
                pass


def test_crashed_holder_releases_lock():
    # A held lock's file descriptor closing (process exit/crash) is what the OS
    # uses to release a flock/LockFileEx lock; simulate it directly instead of
    # any staleness heuristic.
    with tempfile.TemporaryDirectory() as cache_root:
        cache_root = Path(cache_root)
        with _try_venv_lock(cache_root, "key"):
            pass  # lock released on exit, as if the holder had crashed

        entered = []
        with _venv_lock(cache_root, "key"):
            entered.append(True)
        assert entered == [True]


def test_prune_skips_stale_venv_held_by_another_caller():
    with tempfile.TemporaryDirectory() as cache_root:
        cache_root = Path(cache_root)
        venv_dir = cache_root / "key"
        venv_dir.mkdir()
        (venv_dir / ".ready").touch()
        os.utime(venv_dir / ".ready", (0, 0))  # far in the past: stale

        with _venv_lock(cache_root, "key"):
            with patch("quri_sdk_mcp.py_checker.pyright_check.random.random", return_value=0.0):
                _prune_stale_venvs(cache_root)
            assert venv_dir.exists()  # held lock protected it from deletion


def test_prune_deletes_stale_unlocked_venv():
    with tempfile.TemporaryDirectory() as cache_root:
        cache_root = Path(cache_root)
        venv_dir = cache_root / "key"
        venv_dir.mkdir()
        (venv_dir / ".ready").touch()
        os.utime(venv_dir / ".ready", (0, 0))  # far in the past: stale

        with patch("quri_sdk_mcp.py_checker.pyright_check.random.random", return_value=0.0):
            _prune_stale_venvs(cache_root)
        assert not venv_dir.exists()


def test_fresh_marker_within_ttl():
    with tempfile.TemporaryDirectory() as tmp_dir:
        marker = Path(tmp_dir) / ".ready"
        marker.write_text(json.dumps({"created_at": time.time()}))
        assert _is_venv_fresh(marker)


def test_stale_marker_past_ttl():
    with tempfile.TemporaryDirectory() as tmp_dir:
        marker = Path(tmp_dir) / ".ready"
        marker.write_text(json.dumps({"created_at": time.time() - 999999999}))
        assert not _is_venv_fresh(marker)


def test_touching_marker_refreshes_mtime_but_not_created_at():
    with tempfile.TemporaryDirectory() as tmp_dir:
        marker = Path(tmp_dir) / ".ready"
        created_at = time.time() - 3600
        marker.write_text(json.dumps({"created_at": created_at}))
        old_mtime = marker.stat().st_mtime
        os.utime(marker, (old_mtime - 1000, old_mtime - 1000))

        marker.touch()

        assert marker.stat().st_mtime > old_mtime - 1000
        assert json.loads(marker.read_text())["created_at"] == created_at


if __name__ == "__main__":
    test_lock_excludes_concurrent_entry()
    test_held_lock_blocks_try_lock()
    test_crashed_holder_releases_lock()
    test_prune_skips_stale_venv_held_by_another_caller()
    test_prune_deletes_stale_unlocked_venv()
    test_fresh_marker_within_ttl()
    test_stale_marker_past_ttl()
    test_touching_marker_refreshes_mtime_but_not_created_at()
    print("ok")
