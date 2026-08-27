"""Self-check for the persistent venv cache's lock and freshness-marker logic.

Run directly: `python tests/test_venv_lock.py`.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from quri_sdk_mcp.py_checker.pyright_check import (
    VENV_LOCK_STALE_SECONDS,
    _is_venv_fresh,
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


def test_stale_lock_is_stolen():
    with tempfile.TemporaryDirectory() as cache_root:
        cache_root = Path(cache_root)
        lock_dir = cache_root / "key.lock"
        lock_dir.mkdir()
        stale_time = time.time() - VENV_LOCK_STALE_SECONDS - 1
        os.utime(lock_dir, (stale_time, stale_time))

        entered = []
        with _venv_lock(cache_root, "key"):
            entered.append(True)
        assert entered == [True]


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
    test_stale_lock_is_stolen()
    test_fresh_marker_within_ttl()
    test_stale_marker_past_ttl()
    test_touching_marker_refreshes_mtime_but_not_created_at()
    print("ok")
