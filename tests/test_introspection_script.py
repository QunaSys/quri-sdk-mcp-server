"""Self-check for the introspection_script.py module-path and .pyi parsing.

Run directly: `python tests/test_introspection_script.py`.
"""

import importlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quri_sdk_mcp.introspection_script import (
    _find_ast_node,
    _pyi_path_for_module,
    _pyi_stub_lookup,
    _resolve_module_path,
    introspect_symbol,
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


def test_pyi_path_for_module_walks_up_to_a_resolvable_ancestor():
    # Simulates a compiled leaf module with no importable .py of its own
    # (e.g. a PyO3 submodule that hijacks sys.modules once imported, so
    # find_spec fails on it directly) - the .pyi still sits on disk where
    # a resolvable ancestor package's directory says it should.
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        pkg_dir = root / "fake_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "leaf.pyi").write_text("def f(x: int) -> None: ...")

        sys.path.insert(0, str(root))
        try:
            importlib.invalidate_caches()
            pyi_path = _pyi_path_for_module("fake_pkg.leaf")
        finally:
            sys.path.remove(str(root))
            sys.modules.pop("fake_pkg", None)

    assert pyi_path is not None
    assert pyi_path.name == "leaf.pyi"


def test_introspect_symbol_backfills_docstring_from_pyi_on_partial_success():
    # Reproduces the real-world case: live inspect finds a real signature
    # but no docstring (common for compiled classes without embedded docs),
    # while the sibling .pyi stub does have one.
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "fake_mod.py").write_text(
            "class Foo:\n"
            "    def __init__(self, x: int) -> None:\n"
            "        pass\n"
        )
        (root / "fake_mod.pyi").write_text(
            "class Foo:\n"
            '    """A documented Foo."""\n'
            "    def __init__(self, x: int) -> None: ...\n"
        )

        sys.path.insert(0, str(root))
        try:
            importlib.invalidate_caches()
            result = introspect_symbol("fake_mod.Foo")
        finally:
            sys.path.remove(str(root))
            sys.modules.pop("fake_mod", None)

    assert result["error"] is None
    assert result["source"] == "inspect"
    assert result["signature"] is not None
    assert result["docstring"] == "A documented Foo."


if __name__ == "__main__":
    test_resolve_module_path_splits_module_and_trailing_attrs()
    test_resolve_module_path_returns_module_itself_with_no_remaining_attrs()
    test_find_ast_node_locates_top_level_function()
    test_find_ast_node_locates_nested_method()
    test_pyi_stub_lookup_parses_signature_and_docstring()
    test_pyi_path_for_module_walks_up_to_a_resolvable_ancestor()
    test_introspect_symbol_backfills_docstring_from_pyi_on_partial_success()
    print("ok")
