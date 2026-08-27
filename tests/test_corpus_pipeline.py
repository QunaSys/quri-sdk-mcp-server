"""Self-check for docs-corpus mode selection: classification, title
extraction, search-index parsing, and local-mode building.

Run directly: `python tests/test_corpus_pipeline.py`.
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from quri_sdk_mcp.corpus import db
from quri_sdk_mcp.corpus.pipeline import (
    _classify_category,
    _extract_title,
    _looks_like_docs_checkout,
    _parse_search_index,
    build_local_corpus,
    build_remote_corpus,
    get_corpus,
)


def test_classify_category_matches_known_roots():
    assert _classify_category("docs/tutorials/3_quri-parts/0_basics/index.md") == "tutorial"
    assert _classify_category("docs/examples/0_qsci/index.md") == "example"
    assert _classify_category("docs/community/index.md") == "community"
    assert _classify_category("release-notes/0-19-0.md") == "changelog"
    assert _classify_category("docs/howto/applying_algorithms/page_curve") == "how-to"
    assert _classify_category("docs/reference/some_page") == "reference"
    assert _classify_category("docs/reference/release-notes/index") == "changelog"


def test_classify_category_returns_none_for_unknown_paths():
    assert _classify_category("docs/api/quri_parts.circuit.rst") is None
    assert _classify_category("README.md") is None


def test_extract_title_from_frontmatter():
    body = '---\nslug: 0-19-0\ntitle: 0.19.0\n---\n\nSome content.'
    assert _extract_title(body, "release-notes/0-19-0.md") == "0.19.0"


def test_extract_title_from_first_heading():
    body = "# Introduction to QURI VM\n\nSome content."
    assert _extract_title(body, "docs/tutorials/vm-intro/index.md") == "Introduction to QURI VM"


def test_extract_title_falls_back_to_filename():
    body = "No heading here, just prose."
    assert _extract_title(body, "docs/tutorials/foo/bar.md") == "bar"


def test_parse_search_index_strips_js_wrapper():
    raw = 'Search.setIndex({"docnames": ["docs/tutorials/foo"], "titles": ["Foo"]})'
    index = _parse_search_index(raw)
    assert index["docnames"] == ["docs/tutorials/foo"]
    assert index["titles"] == ["Foo"]


def test_looks_like_docs_checkout():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        assert not _looks_like_docs_checkout(root)
        (root / "docs").mkdir()
        assert _looks_like_docs_checkout(root)


def test_build_local_corpus_indexes_known_folders_only():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        tutorial_dir = root / "docs" / "tutorials" / "circuits"
        tutorial_dir.mkdir(parents=True)
        (tutorial_dir / "index.md").write_text("# Circuits\n\nBuilding a quantum circuit.")

        api_dir = root / "docs" / "api"
        api_dir.mkdir(parents=True)
        (api_dir / "reference.md").write_text("# Reference\n\nUnclassified content.")

        conn = build_local_corpus(root)
        try:
            results = db.query(conn, "circuit")
            assert len(results) == 1
            assert results[0]["category"] == "tutorial"

            assert db.query(conn, "reference") == []
        finally:
            conn.close()


def test_get_corpus_falls_back_to_enterprise_checkout():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        tutorial_dir = root / "docs" / "tutorials" / "circuits"
        tutorial_dir.mkdir(parents=True)
        (tutorial_dir / "index.md").write_text("# Circuits\n\nEnterprise-only content.")

        def fake_get_editable_source(python, package="quri-parts"):
            return root if package == "quri-sdk-enterprise" else None

        with patch(
            "quri_sdk_mcp.corpus.pipeline.get_editable_source",
            side_effect=fake_get_editable_source,
        ):
            conn = asyncio.run(get_corpus(None))
        try:
            results = db.query(conn, "Enterprise")
            assert len(results) == 1
        finally:
            conn.close()


def test_concurrent_remote_rebuilds_do_not_collide():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir) / "docs-corpus.sqlite3"

        async def fake_fetch_page_index():
            return [("docs/tutorials/foo", "Foo")]

        async def fake_fetch_page_text(docname):
            return "Foo content"

        async def run_both():
            return await asyncio.gather(build_remote_corpus(), build_remote_corpus())

        with patch(
            "quri_sdk_mcp.corpus.pipeline._corpus_cache_path", return_value=cache_path
        ), patch(
            "quri_sdk_mcp.corpus.pipeline._fetch_page_index",
            side_effect=fake_fetch_page_index,
        ), patch(
            "quri_sdk_mcp.corpus.pipeline._fetch_page_text",
            side_effect=fake_fetch_page_text,
        ):
            results = asyncio.run(run_both())

        assert all(r == cache_path for r in results)
        assert cache_path.exists()


if __name__ == "__main__":
    test_classify_category_matches_known_roots()
    test_classify_category_returns_none_for_unknown_paths()
    test_extract_title_from_frontmatter()
    test_extract_title_from_first_heading()
    test_extract_title_falls_back_to_filename()
    test_parse_search_index_strips_js_wrapper()
    test_looks_like_docs_checkout()
    test_build_local_corpus_indexes_known_folders_only()
    test_get_corpus_falls_back_to_enterprise_checkout()
    test_concurrent_remote_rebuilds_do_not_collide()
    print("ok")
