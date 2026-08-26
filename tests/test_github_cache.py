"""Self-check for the GitHub API response TTL cache.

Run directly: `python tests/test_github_cache.py`.
"""

from quri_sdk_mcp.fetch.fetcher import GITHUB_CACHE_TTL_SECONDS, _is_github_cache_fresh


def test_fresh_entry_within_ttl():
    assert _is_github_cache_fresh(cached_at=0.0, now=GITHUB_CACHE_TTL_SECONDS - 1)


def test_stale_entry_past_ttl():
    assert not _is_github_cache_fresh(cached_at=0.0, now=GITHUB_CACHE_TTL_SECONDS + 1)


if __name__ == "__main__":
    test_fresh_entry_within_ttl()
    test_stale_entry_past_ttl()
    print("ok")
