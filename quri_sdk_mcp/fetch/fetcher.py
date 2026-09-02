import httpx
from markdownify import MarkdownConverter
from collections import OrderedDict
import importlib.metadata
import os
import time

from quri_sdk_mcp.fetch.types import FetchRequestArgs, FetchResponse


class NoImagesConverter(MarkdownConverter):
    """Create a custom MarkdownConverter that ignores all images during conversion."""

    def convert_img(self, el, text, parent_tags):
        # Return empty string instead of converting the image
        return ""


try:
    _PACKAGE_VERSION = importlib.metadata.version("mcp-server")
except importlib.metadata.PackageNotFoundError:
    _PACKAGE_VERSION = "0.0.0"

GITHUB_API_HOST = "api.github.com"
GITHUB_CACHE_TTL_SECONDS = 15 * 60
GITHUB_CACHE_MAX_ENTRIES = 256
_GitHubCacheKey = tuple[str, tuple[tuple[str, str], ...]]
_github_api_cache: OrderedDict[_GitHubCacheKey, tuple[float, httpx.Response]] = (
    OrderedDict()
)


def _is_github_cache_fresh(cached_at: float, now: float) -> bool:
    return now - cached_at < GITHUB_CACHE_TTL_SECONDS


class Fetcher:
    """Handles fetching and processing web content."""

    DEFAULT_HEADERS = {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 quri-sdk-mcp-server/{_PACKAGE_VERSION} (+https://github.com/QunaSys/quri-sdk-mcp-server)"
    }

    @staticmethod
    async def _fetch(payload: FetchRequestArgs) -> httpx.Response:
        """Internal fetch method using httpx."""
        headers = Fetcher.DEFAULT_HEADERS.copy()
        if payload.headers:
            headers.update(payload.headers)
        headers = httpx.Headers(headers)

        url = str(payload.url)
        is_github_api = payload.url.host == GITHUB_API_HOST

        if is_github_api:
            token = os.environ.get("GITHUB_TOKEN")
            if token and "authorization" not in headers:
                headers["Authorization"] = f"Bearer {token}"

            cache_key: _GitHubCacheKey = (url, tuple(sorted(headers.items())))
            cached = _github_api_cache.get(cache_key)
            if cached is not None:
                cached_at, cached_response = cached
                if _is_github_cache_fresh(cached_at, time.monotonic()):
                    _github_api_cache.move_to_end(cache_key)
                    return cached_response

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            try:
                response = await client.get(
                    url, headers=headers
                )  # HttpUrlをstrに変換
                response.raise_for_status()  # Raises HTTPStatusError for 4xx/5xx responses
                if is_github_api:
                    _github_api_cache[cache_key] = (time.monotonic(), response)
                    _github_api_cache.move_to_end(cache_key)
                    while len(_github_api_cache) > GITHUB_CACHE_MAX_ENTRIES:
                        _github_api_cache.popitem(last=False)
                return response
            except httpx.HTTPStatusError as e:
                raise ConnectionError(
                    f"HTTP error: {e.response.status_code} for url: {e.request.url}"
                ) from e
            except httpx.RequestError as e:
                raise ConnectionError(
                    f"Failed to fetch {payload.url}: {type(e).__name__}"
                ) from e
            except Exception as e:
                # Handle potential URL parsing issues or other unexpected errors
                raise ConnectionError(
                    f"An unexpected error occurred for {payload.url}: {e}"
                ) from e

    @staticmethod
    async def html(payload: FetchRequestArgs) -> FetchResponse:
        """Fetches content as raw HTML."""
        try:
            response = await Fetcher._fetch(payload)
            html_content = await response.aread()  # Read as bytes
            # Try decoding with UTF-8 first, then fallback or use detected encoding
            try:
                html_text = html_content.decode("utf-8")
            except UnicodeDecodeError:
                # Fallback using detected encoding or a robust alternative
                detected_encoding = (
                    response.encoding or "iso-8859-1"
                )  # Default fallback
                html_text = html_content.decode(detected_encoding, errors="replace")

            return FetchResponse(
                content=[{"type": "text", "text": html_text}], isError=False
            )
        except Exception as e:
            return FetchResponse(content=[], isError=True, errorMessage=str(e))

    @staticmethod
    async def markdown(payload: FetchRequestArgs) -> FetchResponse:
        """Fetches content and converts it to Markdown."""
        try:
            response = await Fetcher._fetch(payload)
            html_content = await response.aread()
            # Decode carefully before passing to markdownify
            try:
                html_text = html_content.decode("utf-8")
            except UnicodeDecodeError:
                detected_encoding = response.encoding or "iso-8859-1"
                html_text = html_content.decode(detected_encoding, errors="replace")

            # Use custom NoImagesConverter to ignore images
            converter = NoImagesConverter()
            md = converter.convert(html_text)

            return FetchResponse(content=[{"type": "text", "text": md}], isError=False)
        except Exception as e:
            return FetchResponse(content=[], isError=True, errorMessage=str(e))
