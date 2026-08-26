"""Self-check for the introspection_script.py module-path and .pyi parsing.

Run directly: `python tests/test_introspection_script.py`.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quri_sdk_mcp.introspection_script import (
    _find_ast_node,
    _pyi_stub_lookup,
    _resolve_module_path,
)

_PYI_STUB = '''
def top_level(x: int) -> str: ...

class Sampler:
    def __init__(self, shots: int) -> None:
        """Creates a sampler."""
        ...
    def sample(self, circuit: object) -> dict[int, int]:
        """Runs sampling and returns counts."""
        ...
'''


def test_resolve_module_path_splits_module_and_trailing_attrs():
    module_name, remaining = _resolve_module_path("os.path.join")
    assert module_name == "os.path"
    assert remaining == ["join"]


def test_resolve_module_path_returns_module_itself_with_no_remaining_attrs():
    module_name, remaining = _resolve_module_path("json")
    assert module_name == "json"
    assert remaining == []


def test_find_ast_node_locates_top_level_function():
    import ast

    tree = ast.parse(_PYI_STUB)
    node = _find_ast_node(tree.body, ["top_level"])
    assert node is not None
    assert node.name == "top_level"


def test_find_ast_node_locates_nested_method():
    import ast

    tree = ast.parse(_PYI_STUB)
    node = _find_ast_node(tree.body, ["Sampler", "sample"])
    assert node is not None
    assert node.name == "sample"


def test_pyi_stub_lookup_parses_signature_and_docstring():
    with tempfile.TemporaryDirectory() as tmp_dir:
        so_path = Path(tmp_dir) / "_compiled.cpython-310-darwin.so"
        pyi_path = so_path.with_suffix(".pyi")
        pyi_path.write_text(_PYI_STUB)

        fake_spec = SimpleNamespace(origin=str(so_path))
        with patch("importlib.util.find_spec", return_value=fake_spec):
            result = _pyi_stub_lookup("fake_module", ["Sampler", "sample"])

    assert result is not None
    assert result["signature"] == "def sample(self, circuit: object) -> dict[int, int]"
    assert result["docstring"] == "Runs sampling and returns counts."
    assert result["kind"] == "function"


if __name__ == "__main__":
    test_resolve_module_path_splits_module_and_trailing_attrs()
    test_resolve_module_path_returns_module_itself_with_no_remaining_attrs()
    test_find_ast_node_locates_top_level_function()
    test_find_ast_node_locates_nested_method()
    test_pyi_stub_lookup_parses_signature_and_docstring()
    print("ok")
