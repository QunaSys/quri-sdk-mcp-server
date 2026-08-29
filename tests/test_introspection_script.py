"""Self-check for the introspection_script.py module-path and .pyi parsing.

Run directly: `python tests/test_introspection_script.py`.
"""

import importlib
import importlib.machinery
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quri_sdk_mcp.introspection_script import (
    _check_symbols,
    _find_ast_node,
    _pyi_docstring,
    _pyi_path_for_module,
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


def test_resolve_module_path_bypasses_license_gated_compiled_parent(tmp_path):
    backend_dir = tmp_path / "fake_sdk" / "plus" / "qulacs" / "mpi"
    backend_dir.mkdir(parents=True)
    extension_suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    (backend_dir / f"_backend{extension_suffix}").write_bytes(b"")
    (backend_dir / "_backend.pyi").write_text("class Backend: ...\n")

    sys.path.insert(0, str(tmp_path))
    try:
        with patch("importlib.util.find_spec", side_effect=RuntimeError("licensed")):
            module_name, remaining = _resolve_module_path(
                "fake_sdk.plus.qulacs.mpi._backend.Backend"
            )
    finally:
        sys.path.remove(str(tmp_path))

    assert module_name == "fake_sdk.plus.qulacs.mpi._backend"
    assert remaining == ["Backend"]


def test_check_symbols_checks_exact_symbol_instead_of_parent_namespace():
    availability = _check_symbols(["json.dumps", "json.does_not_exist"])

    assert availability == {"json.dumps": True, "json.does_not_exist": False}


def test_check_symbols_trusts_a_successful_import(tmp_path):
    # A licensed Enterprise install is expected to import cleanly, so
    # availability is now checked by actually importing (see
    # _check_symbols's docstring) rather than avoiding it - this reuses the
    # same live-resolution path as the main lookup.
    package_dir = tmp_path / "fake_plus"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("MPI_BACKEND = object()\n")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        availability = _check_symbols(
            ["fake_plus.MPI_BACKEND", "fake_plus.MISSING"]
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("fake_plus", None)

    assert availability == {
        "fake_plus.MPI_BACKEND": True,
        "fake_plus.MISSING": False,
    }


def test_check_symbols_reports_unavailable_on_import_failure(tmp_path):
    # An installed-but-unlicensed .plus package (or any other import-time
    # failure) must report unavailable, not a false positive from a
    # directory-existence check.
    package_dir = tmp_path / "fake_gated"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        "raise ImportError('LicenseError: no license file found')\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        availability = _check_symbols(["fake_gated.SOMETHING"])
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("fake_gated", None)

    assert availability == {"fake_gated.SOMETHING": False}


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


def test_pyi_docstring_extracts_nested_method_docstring():
    # _pyi_docstring is only ever used to backfill a docstring for an object
    # that already imported successfully, via its own true defining module
    # (see _pyi_lookup_target) - so it no longer parses signatures or
    # follows re-exports, both removed once the "answer without importing"
    # fallback was cut (a trusted, licensed install is expected to import
    # cleanly; see introspect_symbol's docstring).
    with tempfile.TemporaryDirectory() as tmp_dir:
        so_path = Path(tmp_dir) / f"_compiled{importlib.machinery.EXTENSION_SUFFIXES[0]}"
        pyi_path = Path(tmp_dir) / "_compiled.pyi"
        pyi_path.write_text(_PYI_STUB)

        fake_spec = SimpleNamespace(origin=str(so_path))
        with patch("importlib.util.find_spec", return_value=fake_spec):
            docstring = _pyi_docstring("fake_module", ["Sampler", "sample"])

    assert docstring == "Runs sampling and returns counts."


def test_pyi_docstring_is_none_for_a_plain_variable():
    with tempfile.TemporaryDirectory() as tmp_dir:
        so_path = Path(tmp_dir) / f"_compiled{importlib.machinery.EXTENSION_SUFFIXES[0]}"
        pyi_path = Path(tmp_dir) / "_compiled.pyi"
        pyi_path.write_text("MPI_BACKEND: object\n")

        fake_spec = SimpleNamespace(origin=str(so_path))
        with patch("importlib.util.find_spec", return_value=fake_spec):
            docstring = _pyi_docstring("fake_module", ["MPI_BACKEND"])

    # ast.get_docstring only applies to Module/ClassDef/FunctionDef bodies -
    # a bare variable declaration has no docstring to extract, by design.
    assert docstring is None


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


def test_pyi_path_for_compiled_package_does_not_import_parent(tmp_path):
    package_dir = tmp_path / "fake_sdk" / "plus" / "compiled"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.pyi").write_text("class API: ...\n")

    sys.path.insert(0, str(tmp_path))
    try:
        with patch("importlib.util.find_spec", side_effect=RuntimeError("licensed")):
            pyi_path = _pyi_path_for_module("fake_sdk.plus.compiled")
    finally:
        sys.path.remove(str(tmp_path))

    assert pyi_path == package_dir / "__init__.pyi"


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
    assert result["source_text"] == (
        "class Foo:\n"
        "    def __init__(self, x: int) -> None:\n"
        "        pass\n"
    )


def test_introspect_symbol_reports_import_failure_plainly():
    # A trusted, licensed install is expected to import cleanly, so a
    # genuinely failing import (missing package, or an unlicensed
    # Enterprise wheel) is reported as a plain error - there is no static
    # .pyi fallback that tries to answer without importing.
    result = introspect_symbol("not_a_real_package_at_all.Something")

    assert result["error"] is not None
    assert result["source"] is None
    assert result["signature"] is None
    assert result["docstring"] is None


if __name__ == "__main__":
    test_resolve_module_path_splits_module_and_trailing_attrs()
    test_resolve_module_path_returns_module_itself_with_no_remaining_attrs()
    test_find_ast_node_locates_top_level_function()
    test_find_ast_node_locates_nested_method()
    test_pyi_docstring_extracts_nested_method_docstring()
    test_pyi_docstring_is_none_for_a_plain_variable()
    test_pyi_path_for_module_walks_up_to_a_resolvable_ancestor()
    test_introspect_symbol_backfills_docstring_from_pyi_on_partial_success()
    test_introspect_symbol_reports_import_failure_plainly()
    print("ok")
