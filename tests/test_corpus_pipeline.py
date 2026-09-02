"""Self-check for docs-corpus mode selection: classification, title
extraction, search-index parsing, and local-mode building.

Run directly: `python tests/test_corpus_pipeline.py`.
"""

import asyncio
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from quri_sdk_mcp.corpus import db
from quri_sdk_mcp.corpus.pipeline import (
    _classify_category,
    _extract_title,
    _looks_like_docs_checkout,
    _parse_search_index,
    build_local_corpus,
    build_remote_corpus,
    fetch_example_source,
    get_corpus,
    search,
)


def _not_found(url: str) -> ConnectionError:
    """Builds a ConnectionError shaped like the one Fetcher._fetch raises on
    a 404, __cause__ included, since fetch_example_source inspects it to
    decide whether to try the next extension."""
    cause = httpx.HTTPStatusError(
        "404", request=SimpleNamespace(), response=SimpleNamespace(status_code=404)
    )
    error = ConnectionError(f"HTTP error: 404 for url: {url}")
    error.__cause__ = cause
    return error


def test_classify_category_matches_known_roots():
    assert _classify_category("docs/tutorials/3_quri-parts/0_basics/index.md") == "tutorial"
    assert _classify_category("docs/examples/0_qsci/index.md") == "example"
    assert _classify_category("docs/community/index.md") == "community"
    assert _classify_category("release-notes/0-19-0.md") == "changelog"
    assert _classify_category("docs/howto/applying_algorithms/page_curve") == "how-to"
    assert _classify_category("docs/reference/some_page") == "reference"
    assert _classify_category("docs/reference/release-notes/index") == "changelog"


def test_classify_category_returns_none_for_unknown_paths():
    assert _classify_category("docs/unknown/quri_parts.circuit.rst") is None
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


def test_looks_like_docs_checkout_bare_layout():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        assert not _looks_like_docs_checkout(root)
        (root / "tutorials").mkdir()
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

            reference_results = db.query(conn, "reference")
            assert len(reference_results) == 1
            assert reference_results[0]["category"] == "reference"
        finally:
            conn.close()


def test_build_local_corpus_indexes_bare_layout():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        tutorial_dir = root / "tutorials" / "circuits"
        tutorial_dir.mkdir(parents=True)
        (tutorial_dir / "index.md").write_text("# Circuits\n\nBuilding a quantum circuit.")

        conn = build_local_corpus(root)
        try:
            results = db.query(conn, "circuit")
            assert len(results) == 1
            assert results[0]["category"] == "tutorial"
        finally:
            conn.close()


def test_build_local_corpus_indexes_real_sphinx_source_layout_and_notebooks():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        tutorial_dir = root / "docs" / "source" / "docs" / "tutorials"
        tutorial_dir.mkdir(parents=True)
        notebook = {
            "cells": [
                {"cell_type": "markdown", "source": ["# Notebook title\n"]},
                {"cell_type": "code", "source": ["quantum_circuit = object()\n"]},
            ]
        }
        (tutorial_dir / "circuits.ipynb").write_text(json.dumps(notebook))

        conn = build_local_corpus(root)
        try:
            results = db.query(conn, "quantum_circuit")
            assert len(results) == 1
            assert results[0]["path"] == "docs/tutorials/circuits"
            assert results[0]["title"] == "Notebook title"
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
            conn, _ = asyncio.run(get_corpus(None))
        try:
            results = db.query(conn, "Enterprise")
            assert len(results) == 1
        finally:
            conn.close()


def test_get_corpus_survives_malformed_editable_source_metadata():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        tutorial_dir = root / "docs" / "tutorials" / "circuits"
        tutorial_dir.mkdir(parents=True)
        (tutorial_dir / "index.md").write_text("# Circuits\n\nEnterprise-only content.")

        def fake_get_editable_source(python, package="quri-parts"):
            if package == "quri-parts":
                raise json.JSONDecodeError("bad direct_url.json", "", 0)
            return root

        with patch(
            "quri_sdk_mcp.corpus.pipeline.get_editable_source",
            side_effect=fake_get_editable_source,
        ):
            conn, _ = asyncio.run(get_corpus(None))
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


def test_failed_remote_rebuild_preserves_stale_cache():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir) / "docs-corpus.sqlite3"
        conn = sqlite3.connect(cache_path)
        db.create_schema(conn)
        db.insert_doc(conn, "docs/tutorials/old", "tutorial", "Old", "old content")
        conn.commit()
        conn.close()
        stale_time = 1
        os.utime(cache_path, (stale_time, stale_time))

        async def fake_fetch_page_index():
            return [("docs/tutorials/new", "New")]

        async def failed_fetch_page_text(docname):
            raise ConnectionError(docname)

        with patch(
            "quri_sdk_mcp.corpus.pipeline._corpus_cache_path", return_value=cache_path
        ), patch(
            "quri_sdk_mcp.corpus.pipeline._fetch_page_index",
            side_effect=fake_fetch_page_index,
        ), patch(
            "quri_sdk_mcp.corpus.pipeline._fetch_page_text",
            side_effect=failed_fetch_page_text,
        ):
            result = asyncio.run(build_remote_corpus())

        assert result == cache_path
        conn = sqlite3.connect(cache_path)
        try:
            assert db.query(conn, "old")[0]["title"] == "Old"
        finally:
            conn.close()


def test_fetch_example_source_prefers_notebook():
    async def fake_fetch(payload):
        assert payload.url.path.endswith(".ipynb")
        return SimpleNamespace(text='{"cells": []}')

    with patch("quri_sdk_mcp.corpus.pipeline.Fetcher._fetch", side_effect=fake_fetch):
        text = asyncio.run(fetch_example_source("docs/tutorials/quri-parts/circuits"))

    assert text == '{"cells": []}'


def test_fetch_example_source_falls_back_to_markdown_on_404():
    async def fake_fetch(payload):
        if payload.url.path.endswith(".ipynb"):
            raise _not_found(str(payload.url))
        return SimpleNamespace(text="# A how-to page")

    with patch("quri_sdk_mcp.corpus.pipeline.Fetcher._fetch", side_effect=fake_fetch):
        text = asyncio.run(fetch_example_source("docs/howto/some_page"))

    assert text == "# A how-to page"


def test_fetch_example_source_reads_from_local_result_origin():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        tutorial_dir = root / "docs" / "source" / "docs" / "tutorials"
        tutorial_dir.mkdir(parents=True)
        source = '{"cells": [{"source": ["local branch content"]}]}'
        (tutorial_dir / "circuits.ipynb").write_text(source)

        text = asyncio.run(
            fetch_example_source(
                "docs/tutorials/circuits", working_directory=str(root)
            )
        )

    assert text == source


def test_fetch_example_source_handles_dotted_reference_filenames():
    # Sphinx autodoc reference pages are commonly named after the dotted
    # module path itself (e.g. "quri_parts.qulacs.rst"), so the stem alone
    # contains dots that Path.with_suffix would misparse as an extension.
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        api_dir = root / "docs" / "api"
        api_dir.mkdir(parents=True)
        source = "quri_parts.qulacs\n==================\n"
        (api_dir / "quri_parts.qulacs.rst").write_text(source)

        text = asyncio.run(
            fetch_example_source(
                "docs/api/quri_parts.qulacs", working_directory=str(root)
            )
        )

    assert text == source


def test_fetch_example_source_rejects_path_traversal_locally():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "docs" / "tutorials").mkdir(parents=True)

        for bad_path in ("../../etc/passwd", "/etc/passwd"):
            try:
                asyncio.run(
                    fetch_example_source(bad_path, working_directory=str(root))
                )
                assert False, f"expected ValueError for {bad_path!r}"
            except ValueError:
                pass


def test_local_search_returns_origin_for_exact_source_fetch():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        tutorial_dir = root / "docs" / "source" / "docs" / "tutorials"
        tutorial_dir.mkdir(parents=True)
        notebook = {
            "cells": [{"cell_type": "code", "source": ["branch_specific_token"]}]
        }
        (tutorial_dir / "circuits.ipynb").write_text(json.dumps(notebook))

        results = asyncio.run(
            search("branch_specific_token", working_directory=str(root))
        )

    assert results[0]["working_directory"] == str(root)


def test_fetch_example_source_raises_when_neither_extension_exists():
    async def fake_fetch(payload):
        raise _not_found(str(payload.url))

    with patch("quri_sdk_mcp.corpus.pipeline.Fetcher._fetch", side_effect=fake_fetch):
        try:
            asyncio.run(fetch_example_source("docs/does/not/exist"))
            assert False, "expected ConnectionError"
        except ConnectionError:
            pass


def test_working_directory_must_look_like_a_docs_checkout():
    # A caller-supplied working_directory that isn't a QURI SDK docs checkout
    # (e.g. an arbitrary project root) must not be trusted as a read root -
    # it must not silently expose arbitrary local .md/.rst/.ipynb files.
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "README.md").write_text("# Some unrelated project")

        for call in (
            lambda: search("anything", working_directory=str(root)),
            lambda: fetch_example_source("README", working_directory=str(root)),
        ):
            try:
                asyncio.run(call())
                assert False, "expected ValueError for a non-checkout working_directory"
            except ValueError:
                pass


if __name__ == "__main__":
    test_classify_category_matches_known_roots()
    test_classify_category_returns_none_for_unknown_paths()
    test_extract_title_from_frontmatter()
    test_extract_title_from_first_heading()
    test_extract_title_falls_back_to_filename()
    test_parse_search_index_strips_js_wrapper()
    test_looks_like_docs_checkout()
    test_looks_like_docs_checkout_bare_layout()
    test_build_local_corpus_indexes_known_folders_only()
    test_build_local_corpus_indexes_bare_layout()
    test_get_corpus_falls_back_to_enterprise_checkout()
    test_get_corpus_survives_malformed_editable_source_metadata()
    test_concurrent_remote_rebuilds_do_not_collide()
    test_fetch_example_source_prefers_notebook()
    test_fetch_example_source_falls_back_to_markdown_on_404()
    test_fetch_example_source_raises_when_neither_extension_exists()
    test_working_directory_must_look_like_a_docs_checkout()
    print("ok")
