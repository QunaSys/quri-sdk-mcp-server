"""Self-check for target-interpreter and version resolution.

Run directly: `python tests/test_env_resolution.py`.
"""

import importlib.metadata
import os
import sys
from pathlib import Path
from unittest.mock import patch

from quri_sdk_mcp.env_resolution import (
    get_editable_source,
    get_versions,
    resolve_doc_ref,
    resolve_target_python,
)


def test_resolve_target_python_defaults_to_own_interpreter():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("QURI_SDK_MCP_PYTHON", None)
        assert resolve_target_python() == Path(sys.executable)


def test_resolve_target_python_honors_env_override():
    with patch.dict(os.environ, {"QURI_SDK_MCP_PYTHON": "/tmp/other/python"}):
        assert resolve_target_python() == Path("/tmp/other/python")


def test_get_versions_reports_none_for_missing_package():
    def fake_version(name):
        if name == "quri-parts":
            return "17.4.0"
        raise importlib.metadata.PackageNotFoundError(name)

    with patch("importlib.metadata.version", side_effect=fake_version):
        versions = get_versions(Path(sys.executable))

    assert versions["quri-parts"] == "17.4.0"
    assert versions["quri-sdk"] is None


def test_resolve_doc_ref_prefers_quri_parts():
    versions = {"quri-sdk": None, "quri-parts": "17.4.0", "quri-algo": "0.3.0"}
    assert resolve_doc_ref(versions) == "17.4.0"


def test_resolve_doc_ref_falls_back_to_main():
    versions = {"quri-sdk": None, "quri-parts": None, "quri-algo": None}
    assert resolve_doc_ref(versions) == "main"


def test_get_editable_source_returns_none_when_not_editable():
    class FakeDist:
        def read_text(self, name):
            return '{"url": "https://pypi.org/...", "dir_info": {}}'

    with patch(
        "importlib.metadata.Distribution.from_name", return_value=FakeDist()
    ):
        assert get_editable_source(Path(sys.executable)) is None


def test_get_editable_source_returns_path_when_editable():
    class FakeDist:
        def read_text(self, name):
            return (
                '{"url": "file:///Users/dev/quri-parts", '
                '"dir_info": {"editable": true}}'
            )

    with patch(
        "importlib.metadata.Distribution.from_name", return_value=FakeDist()
    ):
        assert get_editable_source(Path(sys.executable)) == Path(
            "/Users/dev/quri-parts"
        )


if __name__ == "__main__":
    test_resolve_target_python_defaults_to_own_interpreter()
    test_resolve_target_python_honors_env_override()
    test_get_versions_reports_none_for_missing_package()
    test_resolve_doc_ref_prefers_quri_parts()
    test_resolve_doc_ref_falls_back_to_main()
    test_get_editable_source_returns_none_when_not_editable()
    test_get_editable_source_returns_path_when_editable()
    print("ok")
