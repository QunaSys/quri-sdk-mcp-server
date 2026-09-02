"""Mode selection and corpus building for `search_docs`/`get_example`.

Two ways to get from "a query" to an FTS5 index to search against, picked
per-call:

- Local mode: walks a local checkout on disk, rebuilt fresh into an
  in-memory connection on every call (no caching - the corpus is small
  enough that this costs single-digit milliseconds, and it guarantees
  results never lag an edit made between calls).
- Remote mode: crawls the public docs site (quri-sdk.qunasys.com) into a
  persistent SQLite cache file, refreshed on a TTL.

Remote mode crawls the deployed site rather than fetching source markdown
from GitHub, for reasons found during implementation: at the time this was
written, the docs source repo (QunaSys/quri-sdk-docusaurus) was private, so
raw-file fetches would 404/403 for the vast majority of this public server's
users who don't hold a QunaSys-scoped GITHUB_TOKEN, and the site's
actually-deployed content didn't match that repo's default branch anyway (it
was built from an in-progress branch). That repo is being retired in favor
of deploying docs straight from the (public) quri-sdk code repo - but since
this crawls the deployed site rather than any particular source repo, it
doesn't care which repo builds the site and needs no update for that move.
The live site is genuinely public and is definitionally always current, so
there's no meaningful per-version ref to resolve here - it's cached as a
single bucket, refreshed on a TTL like the plan's original "main" bucket
idea.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from quri_sdk_mcp.corpus import db
from quri_sdk_mcp.env_resolution import get_editable_source, resolve_target_python
from quri_sdk_mcp.fetch import Fetcher, FetchRequestArgs

DOCS_SITE = "https://quri-sdk.qunasys.com"
CORPUS_REBUILD_TTL_SECONDS = 24 * 60 * 60
CRAWL_CONCURRENCY = 8
MIN_CRAWL_SUCCESS_RATIO = 0.8

# `search`/`get_example` results carry a Sphinx docname `path` (site-relative,
# no extension, e.g. "docs/tutorials/quri-parts/circuits") that maps 1:1 onto
# this source tree per docs/source/_toc.yml. Tried in this order since
# tutorial/how-to pages are increasingly notebook-authored.
_EXAMPLE_SOURCE_BASE = "https://raw.githubusercontent.com/QunaSys/quri-sdk/main/docs/source"
_EXAMPLE_SOURCE_EXTENSIONS = (".ipynb", ".md")

# Path-prefix -> category, most-specific-first, shared by both corpus modes.
# Covers both layouts actually observed: the live site's current
# docs/{concepts,howto,reference,tutorials} structure (reference/release-notes
# nested under reference), and the docs-repo/quri-sdk-enterprise checkout
# structure (top-level tutorials/examples/community/release-notes) that a
# local working_directory may point at.
CATEGORY_ROOTS = [
    ("docs/reference/release-notes", "changelog"),
    ("docs/reference", "reference"),
    ("docs/howto", "how-to"),
    ("docs/tutorials", "tutorial"),
    ("docs/examples", "example"),
    ("docs/concepts", "concept"),
    ("docs/community", "community"),
    ("docs/api", "reference"),
    ("docs/quri_parts", "reference"),
    ("docs/quri_algo", "reference"),
    ("docs/quri_vm", "reference"),
    ("release-notes", "changelog"),
    ("tutorials", "tutorial"),
    ("examples", "example"),
    ("community", "community"),
]

# Top-level dirs a local working_directory is walked for, covering both the
# live site's "docs/{category}" layout and the docs-repo/quri-sdk-enterprise
# checkout's bare top-level layout described above.
_LOCAL_ROOT_DIRS = ("docs", "release-notes", "tutorials", "examples", "community")


def _classify_category(path: str) -> Optional[str]:
    """Maps a repo/site-relative path to a corpus category by its root folder."""
    for root, category in CATEGORY_ROOTS:
        if path == root or path.startswith(root + "/"):
            return category
    return None


def _extract_title(body: str, path: str) -> str:
    """Extracts a title: YAML frontmatter `title:`, else the first H1, else
    the filename. Used for local mode, where content is raw markdown."""
    text = body
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
            match = re.search(r"^title:\s*(.+)$", frontmatter, re.MULTILINE)
            if match:
                return match.group(1).strip().strip("\"'")
            text = text[end + 4:]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    lines = text.splitlines()
    for title, underline in zip(lines, lines[1:]):
        if title.strip() and re.fullmatch(r"[=\-~^]+", underline.strip()):
            return title.strip()
    return Path(path).stem


def _notebook_text(raw: str) -> str:
    """Extracts searchable Markdown and code from a notebook JSON document."""
    notebook = json.loads(raw)
    chunks = []
    for cell in notebook.get("cells", []):
        source = cell.get("source", "")
        chunks.append("".join(source) if isinstance(source, list) else source)
    return "\n\n".join(chunks)


def _docs_content_root(working_directory: Path) -> Path:
    """Returns the directory whose children use deployed Sphinx doc paths."""
    sphinx_source = working_directory / "docs" / "source"
    return sphinx_source if sphinx_source.is_dir() else working_directory


def _corpus_cache_path() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    root = Path(cache_home) / "quri-sdk-mcp"
    root.mkdir(parents=True, exist_ok=True)
    return root / "docs-corpus.sqlite3"


def _parse_search_index(raw: str) -> dict:
    """Parses Sphinx's `Search.setIndex({...})` JS-wrapped search index."""
    text = raw.strip()
    payload = text[len("Search.setIndex("):-1] if text.startswith("Search.setIndex(") else text
    return json.loads(payload)


def _clean_title(raw_title: str) -> str:
    """Strips embedded HTML (Sphinx titles can contain markup, e.g. for
    math) and unescapes entities, e.g. "Foo &amp; Bar" -> "Foo & Bar"."""
    return BeautifulSoup(raw_title, "html.parser").get_text()


async def _fetch_page_index() -> list[tuple[str, str]]:
    """Fetches the Sphinx search index and returns (docname, title) pairs for
    every page classifiable into a known category."""
    response = await Fetcher._fetch(FetchRequestArgs(url=f"{DOCS_SITE}/searchindex.js"))
    index = _parse_search_index(response.text)
    docnames = index.get("docnames", [])
    titles = index.get("titles", [])
    return [
        (docname, _clean_title(title))
        for docname, title in zip(docnames, titles)
        if _classify_category(docname) is not None
    ]


async def _fetch_page_text(docname: str) -> str:
    """Fetches one page's rendered HTML and extracts its main article text."""
    response = await Fetcher._fetch(FetchRequestArgs(url=f"{DOCS_SITE}/{docname}.html"))
    soup = BeautifulSoup(response.text, "lxml")
    article = soup.select_one("article") or soup
    for tag in article(["script", "style"]):
        tag.decompose()
    return article.get_text(separator=" ", strip=True)


def _write_corpus_cache(
    cache_path: Path, pages: list[tuple[str, str]], bodies: list[Optional[str]]
) -> Path:
    """Writes a fresh corpus SQLite cache file. Blocking; run via to_thread."""
    fd, tmp_name = tempfile.mkstemp(
        dir=cache_path.parent, prefix=cache_path.stem + ".", suffix=".tmp"
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    conn = sqlite3.connect(tmp_path)
    try:
        db.create_schema(conn)
        for (docname, title), body in zip(pages, bodies):
            if body is not None:
                db.insert_doc(conn, docname, _classify_category(docname), title, body)
        conn.commit()
    finally:
        conn.close()
    tmp_path.replace(cache_path)
    return cache_path


async def build_remote_corpus() -> Path:
    """Builds (or reuses) the persistent live-site docs corpus cache.

    Rebuilt if the cache file is older than `CORPUS_REBUILD_TTL_SECONDS`,
    since the live site's content changes over time.

    Returns:
        Path to the populated SQLite cache file.
    """
    cache_path = _corpus_cache_path()
    if cache_path.exists():
        if time.time() - cache_path.stat().st_mtime < CORPUS_REBUILD_TTL_SECONDS:
            return cache_path

    had_stale_cache = cache_path.exists()
    try:
        pages = await _fetch_page_index()
    except Exception:
        if had_stale_cache:
            return cache_path
        raise

    semaphore = asyncio.Semaphore(CRAWL_CONCURRENCY)

    async def _fetch_bounded(docname: str) -> Optional[str]:
        async with semaphore:
            try:
                return await _fetch_page_text(docname)
            except Exception:
                # One page failing (transient network error, etc.) shouldn't
                # sink the whole crawl - it's just missing from this build.
                return None

    bodies = await asyncio.gather(*(_fetch_bounded(docname) for docname, _ in pages))

    successful_pages = sum(body is not None for body in bodies)
    success_ratio = successful_pages / len(pages) if pages else 0.0
    if success_ratio < MIN_CRAWL_SUCCESS_RATIO:
        if had_stale_cache:
            return cache_path
        raise ConnectionError(
            f"Documentation crawl fetched only {successful_pages}/{len(pages)} pages"
        )

    return await asyncio.to_thread(_write_corpus_cache, cache_path, pages, bodies)


def build_local_corpus(working_directory: Path) -> sqlite3.Connection:
    """Builds an in-memory docs corpus from a local checkout, fresh on every
    call (see module docstring for why this isn't cached)."""
    # check_same_thread=False: this runs inside asyncio.to_thread and hands
    # the connection back to the caller's (event-loop) thread; usage is
    # handed off sequentially, never concurrent, so this is safe.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db.create_schema(conn)
    content_root = _docs_content_root(working_directory)
    indexed_paths = set()
    for root_name in _LOCAL_ROOT_DIRS:
        root_dir = content_root / root_name
        if not root_dir.is_dir():
            continue
        for suffix in (".ipynb", ".md", ".rst"):
            for source_path in root_dir.rglob(f"*{suffix}"):
                rel_path = source_path.relative_to(content_root).as_posix()
                result_path = str(PurePosixPath(rel_path).with_suffix(""))
                category = _classify_category(rel_path)
                if category is None or result_path in indexed_paths:
                    continue
                raw = source_path.read_text(encoding="utf-8", errors="replace")
                try:
                    body = _notebook_text(raw) if suffix == ".ipynb" else raw
                except json.JSONDecodeError:
                    continue
                db.insert_doc(
                    conn,
                    result_path,
                    category,
                    _extract_title(body, rel_path),
                    body,
                )
                indexed_paths.add(result_path)
    conn.commit()
    return conn


def _looks_like_docs_checkout(path: Path) -> bool:
    content_root = _docs_content_root(path)
    return any((content_root / root_name).is_dir() for root_name in _LOCAL_ROOT_DIRS)


def _find_docs_checkout(path: Path) -> Path | None:
    """Finds a checkout root at `path` or a nearby monorepo ancestor."""
    candidates = (path, *list(path.parents)[:3])
    return next((candidate for candidate in candidates if _looks_like_docs_checkout(candidate)), None)


async def _resolve_local_checkout(working_directory: Optional[str]) -> Path | None:
    if working_directory is not None:
        checkout = _find_docs_checkout(Path(working_directory))
        if checkout is None:
            raise ValueError(
                f"{working_directory!r} does not look like a QURI SDK "
                "documentation checkout (no docs/release-notes/tutorials/"
                "examples/community directory found there or in a nearby "
                "ancestor)"
            )
        return checkout

    python = resolve_target_python()
    for package in ("quri-parts", "quri-sdk-enterprise"):
        try:
            editable_source = await asyncio.to_thread(
                get_editable_source, python, package
            )
        except (subprocess.CalledProcessError, OSError, json.JSONDecodeError):
            continue
        if editable_source is not None:
            checkout = _find_docs_checkout(editable_source)
            if checkout is not None:
                return checkout
    return None


async def _remote_corpus() -> sqlite3.Connection:
    cache_path = await build_remote_corpus()
    conn = sqlite3.connect(cache_path)
    if db.docs_table_is_fts5(conn) != db.FTS5_AVAILABLE:
        conn.close()
        cache_path.unlink(missing_ok=True)
        cache_path = await build_remote_corpus()
        conn = sqlite3.connect(cache_path)
    return conn


async def get_corpus(working_directory: Optional[str]) -> sqlite3.Connection:
    """Resolves an open, populated corpus connection.

    Selection order:
    1. `working_directory` given explicitly - search it directly.
    2. Else, if the target interpreter has an editable `quri-parts` or
       `quri-sdk-enterprise` install whose resolved local path itself
       contains recognizable doc content (a `docs/` or `release-notes/`
       directory next to it) - search that.
    3. Else, the persistent live-site crawl cache.
    """
    local_checkout = await _resolve_local_checkout(working_directory)
    if local_checkout is not None:
        return await asyncio.to_thread(build_local_corpus, local_checkout)
    return await _remote_corpus()


async def search(
    query: str,
    categories: Optional[list[str]] = None,
    limit: int = 10,
    working_directory: Optional[str] = None,
) -> list[dict[str, str]]:
    """Resolves a corpus (see `get_corpus`) and searches it."""
    local_checkout = await _resolve_local_checkout(working_directory)
    if local_checkout is not None:
        conn = await asyncio.to_thread(build_local_corpus, local_checkout)
    else:
        conn = await _remote_corpus()
    try:
        results = db.query(conn, query, categories=categories, limit=limit)
        if local_checkout is not None:
            for result in results:
                result["working_directory"] = str(local_checkout)
        return results
    finally:
        conn.close()


def _fetch_local_source(path: str, working_directory: Path) -> str:
    content_root = _docs_content_root(working_directory).resolve()
    relative_path = PurePosixPath(path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Example path must stay within the documentation checkout")
    base_path = content_root.joinpath(*relative_path.parts)
    known_extensions = (*_EXAMPLE_SOURCE_EXTENSIONS, ".rst")
    candidates = (
        (base_path,)
        if base_path.name.endswith(known_extensions)
        else tuple(base_path.parent / (base_path.name + ext) for ext in known_extensions)
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(content_root):
            raise ValueError("Example path must stay within the documentation checkout")
        if resolved.is_file():
            return resolved.read_text(encoding="utf-8", errors="replace")
    raise ConnectionError(f"No local notebook or documentation source found for {path!r}")


async def fetch_example_source(
    path: str, working_directory: Optional[str] = None
) -> str:
    """Fetches the raw source behind a `search`/`get_example` result's
    `path`, notebook first, falling back to markdown for pages that aren't
    notebook-authored.

    Args:
        path: A `path` value as returned by `search`/`get_example`, e.g.
            "docs/tutorials/quri-parts/circuits".

    Returns:
        The raw file text (`.ipynb` JSON, Markdown, or RST), verbatim.

    Raises:
        ConnectionError: if neither extension exists at `path`, or the
            request otherwise fails.
    """
    local_checkout = await _resolve_local_checkout(working_directory)
    if local_checkout is not None:
        return await asyncio.to_thread(_fetch_local_source, path, local_checkout)

    relative_path = PurePosixPath(path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Example path must stay within the documentation source tree")
    # `path` is a dotted-module-safe docname (e.g. "docs/api/quri_parts.qulacs")
    # and may itself contain dots that aren't a file extension, so only strip
    # one if it's actually a known extension - mirrors _fetch_local_source.
    known_extensions = (*_EXAMPLE_SOURCE_EXTENSIONS, ".rst")
    path_without_suffix = (
        str(relative_path.with_suffix(""))
        if relative_path.name.endswith(known_extensions)
        else str(relative_path)
    )
    last_error: Optional[ConnectionError] = None
    for suffix in known_extensions:
        url = f"{_EXAMPLE_SOURCE_BASE}/{path_without_suffix}{suffix}"
        try:
            response = await Fetcher._fetch(FetchRequestArgs(url=url))
            return response.text
        except ConnectionError as e:
            cause = e.__cause__
            if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 404:
                last_error = e
                continue
            raise
    assert last_error is not None
    raise last_error
