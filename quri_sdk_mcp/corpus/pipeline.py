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
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from quri_sdk_mcp.corpus import db
from quri_sdk_mcp.env_resolution import get_editable_source, resolve_target_python
from quri_sdk_mcp.fetch import Fetcher, FetchRequestArgs

DOCS_SITE = "https://quri-sdk.qunasys.com"
CORPUS_REBUILD_TTL_SECONDS = 24 * 60 * 60
CRAWL_CONCURRENCY = 8

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
    return Path(path).stem


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

    pages = await _fetch_page_index()

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

    return await asyncio.to_thread(_write_corpus_cache, cache_path, pages, bodies)


def build_local_corpus(working_directory: Path) -> sqlite3.Connection:
    """Builds an in-memory docs corpus from a local checkout, fresh on every
    call (see module docstring for why this isn't cached)."""
    # check_same_thread=False: this runs inside asyncio.to_thread and hands
    # the connection back to the caller's (event-loop) thread; usage is
    # handed off sequentially, never concurrent, so this is safe.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db.create_schema(conn)
    for root_name in _LOCAL_ROOT_DIRS:
        root_dir = working_directory / root_name
        if not root_dir.is_dir():
            continue
        for md_path in root_dir.rglob("*.md"):
            rel_path = md_path.relative_to(working_directory).as_posix()
            category = _classify_category(rel_path)
            if category is None:
                continue
            body = md_path.read_text(encoding="utf-8", errors="replace")
            db.insert_doc(conn, rel_path, category, _extract_title(body, rel_path), body)
    conn.commit()
    return conn


def _looks_like_docs_checkout(path: Path) -> bool:
    return any((path / root_name).is_dir() for root_name in _LOCAL_ROOT_DIRS)


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
    if working_directory is not None:
        return await asyncio.to_thread(build_local_corpus, Path(working_directory))

    python = resolve_target_python()
    for package in ("quri-parts", "quri-sdk-enterprise"):
        try:
            editable_source = await asyncio.to_thread(
                get_editable_source, python, package
            )
        except (subprocess.CalledProcessError, OSError, json.JSONDecodeError):
            continue
        if editable_source is not None and _looks_like_docs_checkout(editable_source):
            return await asyncio.to_thread(build_local_corpus, editable_source)

    cache_path = await build_remote_corpus()
    conn = sqlite3.connect(cache_path)
    if db.docs_table_is_fts5(conn) != db.FTS5_AVAILABLE:
        # Cache file was built by a process with different FTS5 support;
        # rebuild it so this process's schema expectations match reality.
        conn.close()
        cache_path.unlink(missing_ok=True)
        cache_path = await build_remote_corpus()
        conn = sqlite3.connect(cache_path)
    return conn


async def search(
    query: str,
    categories: Optional[list[str]] = None,
    limit: int = 10,
    working_directory: Optional[str] = None,
) -> list[dict[str, str]]:
    """Resolves a corpus (see `get_corpus`) and searches it."""
    conn = await get_corpus(working_directory)
    try:
        return db.query(conn, query, categories=categories, limit=limit)
    finally:
        conn.close()


async def fetch_example_source(path: str) -> str:
    """Fetches the raw source behind a `search`/`get_example` result's
    `path`, notebook first, falling back to markdown for pages that aren't
    notebook-authored.

    Args:
        path: A `path` value as returned by `search`/`get_example`, e.g.
            "docs/tutorials/quri-parts/circuits".

    Returns:
        The raw file text (`.ipynb` JSON or markdown), verbatim.

    Raises:
        ConnectionError: if neither extension exists at `path`, or the
            request otherwise fails.
    """
    last_error: Optional[ConnectionError] = None
    for suffix in _EXAMPLE_SOURCE_EXTENSIONS:
        url = f"{_EXAMPLE_SOURCE_BASE}/{path}{suffix}"
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
