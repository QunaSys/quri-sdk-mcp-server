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


def test_check_symbols_does_not_import_compiled_parent(tmp_path):
    mpi_dir = tmp_path / "fake_sdk" / "plus" / "qulacs" / "mpi"
    mpi_dir.mkdir(parents=True)
    extension_suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    (mpi_dir.parent / f"__init__{extension_suffix}").write_bytes(b"")
    (mpi_dir.parent / "__init__.pyi").write_text("")
    (mpi_dir / f"__init__{extension_suffix}").write_bytes(b"")
    (mpi_dir / "__init__.pyi").write_text(
        "from ._backend import MPI_BACKEND as MPI_BACKEND\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        with patch(
            "importlib.util.find_spec",
            side_effect=AssertionError("compiled parent must not be imported"),
        ):
            availability = _check_symbols(
                [
                    "fake_sdk.plus.qulacs.mpi.MPI_BACKEND",
                    "fake_sdk.plus.qulacs.mpi.MISSING",
                ]
            )
    finally:
        sys.path.remove(str(tmp_path))

    assert availability == {
        "fake_sdk.plus.qulacs.mpi.MPI_BACKEND": True,
        "fake_sdk.plus.qulacs.mpi.MISSING": False,
    }


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
        so_path = Path(tmp_dir) / f"_compiled{importlib.machinery.EXTENSION_SUFFIXES[0]}"
        pyi_path = Path(tmp_dir) / "_compiled.pyi"
        pyi_path.write_text(_PYI_STUB)

        fake_spec = SimpleNamespace(origin=str(so_path))
        with patch("importlib.util.find_spec", return_value=fake_spec):
            result = _pyi_stub_lookup("fake_module", ["Sampler", "sample"])

    assert result is not None
    assert result["signature"] == "def sample(self, circuit: object) -> dict[int, int]"
    assert result["docstring"] == "Runs sampling and returns counts."
    assert result["kind"] == "function"


def test_pyi_stub_lookup_parses_compiled_class_constructor_signature():
    with tempfile.TemporaryDirectory() as tmp_dir:
        so_path = Path(tmp_dir) / f"_compiled{importlib.machinery.EXTENSION_SUFFIXES[0]}"
        pyi_path = Path(tmp_dir) / "_compiled.pyi"
        pyi_path.write_text(_PYI_STUB)

        fake_spec = SimpleNamespace(origin=str(so_path))
        with patch("importlib.util.find_spec", return_value=fake_spec):
            result = _pyi_stub_lookup("fake_module", ["Sampler"])

    assert result is not None
    assert result["signature"] == "(shots: int)"
    assert result["kind"] == "class"


def test_pyi_stub_lookup_follows_package_variable_reexport(tmp_path):
    package_dir = tmp_path / "fake_plus"
    package_dir.mkdir()
    extension_suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    init_extension = package_dir / f"__init__{extension_suffix}"
    backend_extension = package_dir / f"_backend{extension_suffix}"
    init_extension.write_bytes(b"")
    backend_extension.write_bytes(b"")
    (package_dir / "__init__.pyi").write_text(
        "from ._backend import MPI_BACKEND as MPI_BACKEND\n"
    )
    (package_dir / "_backend.pyi").write_text("MPI_BACKEND: object\n")

    def find_spec(name):
        if name == "fake_plus":
            return SimpleNamespace(
                origin=str(init_extension),
                submodule_search_locations=[str(package_dir)],
            )
        if name == "fake_plus._backend":
            return SimpleNamespace(
                origin=str(backend_extension),
                submodule_search_locations=None,
            )
        return None

    with patch("importlib.util.find_spec", side_effect=find_spec):
        result = _pyi_stub_lookup("fake_plus", ["MPI_BACKEND"])

    assert result is not None
    assert result["signature"] == "MPI_BACKEND: object"
    assert result["kind"] == "variable"
    assert result["source_file"].endswith("_backend.pyi")


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


def test_pyi_stub_lookup_has_no_source_text():
    # A .pyi stub only has declarations, not an implementation - lookup_api
    # must report that honestly rather than returning the stub text itself.
    with tempfile.TemporaryDirectory() as tmp_dir:
        so_path = Path(tmp_dir) / f"_compiled{importlib.machinery.EXTENSION_SUFFIXES[0]}"
        pyi_path = Path(tmp_dir) / "_compiled.pyi"
        pyi_path.write_text(_PYI_STUB)

        fake_spec = SimpleNamespace(origin=str(so_path))
        with patch("importlib.util.find_spec", return_value=fake_spec):
            result = _pyi_stub_lookup("fake_module", ["Sampler", "sample"])

    assert result is not None
    assert result["source_text"] is None


if __name__ == "__main__":
    test_resolve_module_path_splits_module_and_trailing_attrs()
    test_resolve_module_path_returns_module_itself_with_no_remaining_attrs()
    test_find_ast_node_locates_top_level_function()
    test_find_ast_node_locates_nested_method()
    test_pyi_stub_lookup_parses_signature_and_docstring()
    test_pyi_stub_lookup_parses_compiled_class_constructor_signature()
    test_pyi_path_for_module_walks_up_to_a_resolvable_ancestor()
    test_introspect_symbol_backfills_docstring_from_pyi_on_partial_success()
    test_pyi_stub_lookup_has_no_source_text()
    print("ok")
