"""Self-check for the GitHub API response TTL cache.

Run directly: `python tests/test_github_cache.py`.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from quri_sdk_mcp.fetch.fetcher import (
    GITHUB_CACHE_TTL_SECONDS,
    Fetcher,
    _github_api_cache,
    _is_github_cache_fresh,
)
from quri_sdk_mcp.fetch.types import FetchRequestArgs


def test_fresh_entry_within_ttl():
    assert _is_github_cache_fresh(cached_at=0.0, now=GITHUB_CACHE_TTL_SECONDS - 1)


def test_stale_entry_past_ttl():
    assert not _is_github_cache_fresh(cached_at=0.0, now=GITHUB_CACHE_TTL_SECONDS + 1)


def _fake_client(response):
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _fake_response():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    return response


def test_caller_authorization_header_not_overwritten():
    _github_api_cache.clear()
    payload = FetchRequestArgs(
        url="https://api.github.com/repos/x/y",
        headers={"Authorization": "custom-token"},
    )
    with patch.dict("os.environ", {"GITHUB_TOKEN": "env-token"}), patch(
        "httpx.AsyncClient", return_value=_fake_client(_fake_response())
    ) as client_cls:
        asyncio.run(Fetcher._fetch(payload))
    sent_headers = client_cls.return_value.get.call_args.kwargs["headers"]
    assert sent_headers["Authorization"] == "custom-token"


def test_different_headers_produce_different_cache_entries():
    _github_api_cache.clear()
    url = "https://api.github.com/repos/x/y"
    for header_value in ("a", "b"):
        payload = FetchRequestArgs(url=url, headers={"X-Test": header_value})
        with patch(
            "httpx.AsyncClient", return_value=_fake_client(_fake_response())
        ):
            asyncio.run(Fetcher._fetch(payload))
    assert len(_github_api_cache) == 2


if __name__ == "__main__":
    test_fresh_entry_within_ttl()
    test_stale_entry_past_ttl()
    test_caller_authorization_header_not_overwritten()
    test_different_headers_produce_different_cache_entries()
    print("ok")
