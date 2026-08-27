"""SQLite FTS5 schema and query layer for the docs corpus.

Shared by both corpus modes (`pipeline.py`): one writes to a persistent
file, the other to an in-memory `:memory:` connection.
"""

from __future__ import annotations

import sqlite3
import warnings
from typing import Optional

_FTS5_SCHEMA = (
    "CREATE VIRTUAL TABLE docs USING fts5("
    "path, category, title, body, tokenize='porter unicode61')"
)
_FALLBACK_SCHEMA = "CREATE TABLE docs (path TEXT, category TEXT, title TEXT, body TEXT)"


def _fts5_available() -> bool:
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        probe.close()


FTS5_AVAILABLE = _fts5_available()

if not FTS5_AVAILABLE:
    warnings.warn(
        "sqlite3 was built without FTS5 support; the docs corpus falls back "
        "to a plain LIKE-based search (no ranking, no stemming).",
        RuntimeWarning,
    )


def create_schema(conn: sqlite3.Connection) -> None:
    """Creates the (empty) docs table for a fresh corpus connection."""
    conn.execute(_FTS5_SCHEMA if FTS5_AVAILABLE else _FALLBACK_SCHEMA)


def docs_table_is_fts5(conn: sqlite3.Connection) -> bool:
    """Inspects the actual on-disk schema of an existing `docs` table, rather
    than trusting this process's own `FTS5_AVAILABLE` - a persistent cache
    file may have been built by a different process/interpreter."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'docs'"
    ).fetchone()
    if row is None or row[0] is None:
        return FTS5_AVAILABLE
    return "VIRTUAL TABLE" in row[0].upper()


def insert_doc(conn: sqlite3.Connection, path: str, category: str, title: str, body: str) -> None:
    """Adds one document to the corpus."""
    conn.execute(
        "INSERT INTO docs (path, category, title, body) VALUES (?, ?, ?, ?)",
        (path, category, title, body),
    )


def _sanitize_fts_query(terms: str) -> str:
    """Quotes each token so arbitrary user input can't break FTS5 syntax."""
    return " ".join('"' + token.replace('"', '""') + '"' for token in terms.split())


def _escape_like(terms: str) -> str:
    """Escapes SQL LIKE metacharacters so `terms` is matched literally."""
    return terms.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def query(
    conn: sqlite3.Connection,
    terms: str,
    categories: Optional[list[str]] = None,
    limit: int = 10,
) -> list[dict[str, str]]:
    """Searches the docs corpus.

    Args:
        conn: An open, already-populated corpus connection.
        terms: Free-text search query.
        categories: Optional category filter (e.g. ["tutorial", "example"]).
        limit: Max results.

    Returns:
        List of {path, category, title, snippet} dicts, best match first.
    """
    if not terms.strip():
        return []

    params: list = []
    if FTS5_AVAILABLE:
        sql = (
            "SELECT path, category, title, "
            "snippet(docs, 3, '**', '**', '...', 20) AS snippet, "
            "bm25(docs) AS rank FROM docs WHERE docs MATCH ?"
        )
        params.append(_sanitize_fts_query(terms))
    else:
        sql = (
            "SELECT path, category, title, substr(body, 1, 300) AS snippet "
            "FROM docs WHERE body LIKE ? ESCAPE '\\'"
        )
        params.append(f"%{_escape_like(terms)}%")

    if categories:
        sql += f" AND category IN ({','.join('?' for _ in categories)})"
        params.extend(categories)

    sql += " ORDER BY rank LIMIT ?" if FTS5_AVAILABLE else " LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [
        {"path": row[0], "category": row[1], "title": row[2], "snippet": row[3]}
        for row in rows
    ]
