"""Self-check for the FTS5 docs corpus query layer.

Run directly: `python tests/test_fts5_search.py`.
"""

import sqlite3

from quri_sdk_mcp.corpus import db


def _build_sample_corpus() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    db.create_schema(conn)
    db.insert_doc(
        conn, "docs/tutorials/qulacs.md", "tutorial", "Qulacs sampler",
        "How to build a qulacs vector sampler for measurement outcomes.",
    )
    db.insert_doc(
        conn, "docs/examples/bell.md", "example", "Bell state example",
        "A minimal example building a Bell state circuit and sampling it.",
    )
    db.insert_doc(
        conn, "release-notes/0-19-0.md", "changelog", "0.19.0",
        "New features and bug fixes in this release.",
    )
    conn.commit()
    return conn


def test_search_finds_relevant_doc():
    conn = _build_sample_corpus()
    results = db.query(conn, "qulacs sampler")
    assert results
    assert results[0]["path"] == "docs/tutorials/qulacs.md"


def test_category_filter_excludes_other_categories():
    conn = _build_sample_corpus()
    results = db.query(conn, "sampling", categories=["example"])
    assert all(r["category"] == "example" for r in results)
    assert any(r["path"] == "docs/examples/bell.md" for r in results)


def test_no_match_returns_empty():
    conn = _build_sample_corpus()
    assert db.query(conn, "nonexistent_term_xyz") == []


def test_empty_query_returns_empty_without_erroring():
    conn = _build_sample_corpus()
    assert db.query(conn, "   ") == []


def test_query_tolerates_special_characters():
    conn = _build_sample_corpus()
    # Would be a syntax error if passed unsanitized straight into MATCH.
    assert db.query(conn, 'qulacs: "sampler" - test*') == []


if __name__ == "__main__":
    test_search_finds_relevant_doc()
    test_category_filter_excludes_other_categories()
    test_no_match_returns_empty()
    test_empty_query_returns_empty_without_erroring()
    test_query_tolerates_special_characters()
    print("ok")
