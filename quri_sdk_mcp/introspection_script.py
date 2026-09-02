"""Stdlib-only introspection script, run inside the *target* interpreter.

Invoked as `python introspection_script.py <dotted.symbol>` by
`quri_sdk_mcp.introspection.lookup_symbol` via subprocess, so it must not
import anything beyond the standard library - it runs inside the user's own
project interpreter, not this server's.

Resolution order for a symbol's signature/docstring:
1. Live `inspect.signature()`/`inspect.getdoc()`, via a real import. This is
   the only path for locating a symbol - OSS packages, editable `.plus` dev
   installs (license checks are compiled out entirely there), and licensed
   compiled `.plus` customer wheels alike. A licensed Enterprise install is
   trusted to import and introspect cleanly (verified empirically:
   Cython-compiled customer wheels do carry real, type-annotated signatures
   and docstrings once imported successfully). If the import fails outright
   - a genuinely missing or unlicensed package - that's reported plainly as
   an error; there is no static fallback that tries to answer without
   importing.
2. If live introspection yields a signature but no docstring (common for
   compiled extension classes - e.g. quri-parts' Rust/PyO3 circuit types -
   that don't embed one), backfill just the docstring from a sibling `.pyi`
   stub, without discarding the real signature. Since this only ever runs
   after a successful import, the stub is located from the live object's
   own `__module__`/`__qualname__` (see `_pyi_lookup_target`) - its true
   defining location, never a re-exporting module, so there's no re-export
   chain to follow. Locating the stub is itself not always a plain
   `find_spec(module).origin` - some native extension modules (e.g. some
   PyO3-built submodules) hijack `sys.modules` for themselves and their
   ancestor packages once imported, so `find_spec` can fail several levels
   up; `_pyi_path_for_module` walks up to the nearest still-resolvable
   ancestor and reconstructs the path from there.

Always prints one JSON object and exits 0, even on failure, so the caller
can treat "symbol not found" as data rather than a subprocess error.
"""

import ast
import importlib
import importlib.machinery
import importlib.util
import inspect
import json
import sys
from pathlib import Path

PLUS_NAMESPACES = ("quri_parts.plus", "quri_algo.plus", "quri_vm.plus")


def _check_plus_namespaces() -> dict:
    """Reports which `.plus` namespaces are importable in this interpreter."""
    namespaces = {}
    for name in PLUS_NAMESPACES:
        try:
            namespaces[name] = importlib.util.find_spec(name) is not None
        except Exception:
            namespaces[name] = False
    return namespaces


def _check_symbols(symbols: list[str]) -> dict[str, bool]:
    """Reports whether each exact dotted symbol actually resolves.

    Trusts that a valid Enterprise license is present rather than avoiding
    the import - reuses the same live-resolution path as the main lookup,
    so an installed-but-unlicensed `.plus` package correctly reports
    unavailable instead of a false positive from a directory-existence check.
    """
    availability = {}
    for symbol in symbols:
        try:
            module_name, remaining_attrs = _resolve_module_path(symbol)
            _live_object(module_name, remaining_attrs)
            availability[symbol] = True
        except Exception:
            availability[symbol] = False
    return availability


def _walk_resolvable_prefixes(dotted: str):
    """Yields (candidate, spec, remaining_attrs) for each dotted-name prefix of
    `dotted`, longest first, that resolves to a locatable module via `find_spec`.

    Python can import a candidate's parent while resolving it. Exceptions from
    license-gated compiled parents are ignored so filesystem resolution can be
    used instead.
    """
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        try:
            spec = importlib.util.find_spec(candidate)
        except Exception:
            spec = None
        if spec is not None:
            yield candidate, spec, parts[i:]


def _resolve_module_path_on_sys_path(dotted: str) -> tuple[str, list[str]] | None:
    """Finds the deepest installed module path without importing packages."""
    parts = dotted.split(".")
    locations = [Path(entry) for entry in sys.path if entry and Path(entry).is_dir()]
    module_suffixes = [".pyi", ".py", *importlib.machinery.EXTENSION_SUFFIXES]

    for index, part in enumerate(parts):
        package_dirs = [location / part for location in locations]
        package_dirs = [path for path in package_dirs if path.is_dir()]
        if package_dirs:
            locations = package_dirs
            continue

        if any(
            (location / f"{part}{suffix}").is_file()
            for location in locations
            for suffix in module_suffixes
        ):
            return ".".join(parts[: index + 1]), parts[index + 1 :]

        if index:
            return ".".join(parts[:index]), parts[index:]
        return None

    return dotted, []


def _resolve_module_path(dotted: str) -> tuple[str, list[str]]:
    """Splits a dotted symbol into its module path and remaining attributes.

    Tries the longest prefix of `dotted` that resolves to a locatable module.

    Returns:
        (module_name, remaining_attrs) - remaining_attrs is empty if `dotted`
        names a module itself.
    """
    filesystem_result = _resolve_module_path_on_sys_path(dotted)
    import_result = next(
        (
            (candidate, remaining)
            for candidate, _spec, remaining in _walk_resolvable_prefixes(dotted)
        ),
        None,
    )
    if filesystem_result is not None and (
        import_result is None
        or len(filesystem_result[0].split(".")) > len(import_result[0].split("."))
    ):
        return filesystem_result
    if import_result is not None:
        return import_result
    if filesystem_result is not None:
        return filesystem_result
    raise ModuleNotFoundError(
        f"No importable module prefix found for {dotted!r}"
    )


def _live_object(module_name: str, remaining_attrs: list[str]):
    """Resolves the live object for a module path + remaining attribute chain.

    Force-imports intermediate submodules that aren't auto-exposed as
    attributes of their parent package.
    """
    obj = importlib.import_module(module_name)
    current_module_name = module_name
    for attr in remaining_attrs:
        try:
            obj = getattr(obj, attr)
        except AttributeError:
            current_module_name = f"{current_module_name}.{attr}"
            obj = importlib.import_module(current_module_name)
    return obj


def _kind_of(obj) -> str:
    if inspect.isclass(obj):
        return "class"
    if inspect.ismodule(obj):
        return "module"
    if inspect.iscoroutinefunction(obj) or inspect.isfunction(obj):
        return "function"
    if inspect.ismethod(obj) or inspect.ismethoddescriptor(obj):
        return "method"
    if inspect.isbuiltin(obj):
        return "builtin_function"
    return type(obj).__name__


def _inspect_live(obj) -> dict:
    """Live-introspects an object. `signature` is None if unavailable."""
    try:
        signature = str(inspect.signature(obj))
    except (TypeError, ValueError):
        signature = None

    try:
        source_file = inspect.getsourcefile(obj)
    except TypeError:
        source_file = None

    source_line = None
    if source_file:
        try:
            _, source_line = inspect.getsourcelines(obj)
        except (TypeError, OSError):
            source_line = None

    try:
        source_text = inspect.getsource(obj)
    except (TypeError, OSError):
        source_text = None

    return {
        "signature": signature,
        "docstring": inspect.getdoc(obj),
        "source_file": source_file,
        "source_line": source_line,
        "source_text": source_text,
        "kind": _kind_of(obj),
    }


def _find_ast_node(body: list, names: list[str]):
    """Walks a `.pyi` AST body to find the FunctionDef/ClassDef for `names`."""
    if not names:
        return None
    target, rest = names[0], names[1:]
    candidates = [
        node
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == target
    ]
    if not candidates:
        return None
    if rest:
        node = candidates[0]
        if isinstance(node, ast.ClassDef):
            return _find_ast_node(node.body, rest)
        return None
    # `@overload` stubs commonly repeat the name with only the last variant
    # carrying a docstring; prefer whichever candidate actually has one.
    return next((node for node in candidates if ast.get_docstring(node)), candidates[0])


def _pyi_sibling(module_path: Path) -> Path:
    """Returns the stub path for a Python or ABI-suffixed extension module."""
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        if module_path.name.endswith(suffix):
            stem = module_path.name[: -len(suffix)]
            return module_path.with_name(f"{stem}.pyi")
    return module_path.with_suffix(".pyi")


def _pyi_path_on_sys_path(module_name: str) -> Path | None:
    """Locates a module or package stub directly from interpreter paths."""
    parts = module_name.split(".")
    locations = [Path(entry) for entry in sys.path if entry and Path(entry).is_dir()]

    for index, part in enumerate(parts):
        package_dirs = [location / part for location in locations]
        package_dirs = [path for path in package_dirs if path.is_dir()]
        if package_dirs:
            if index == len(parts) - 1:
                for package_dir in package_dirs:
                    stub = package_dir / "__init__.pyi"
                    if stub.is_file():
                        return stub
                return None
            locations = package_dirs
            continue

        if index != len(parts) - 1:
            return None
        for location in locations:
            stub = location / f"{part}.pyi"
            if stub.is_file():
                return stub
            for suffix in importlib.machinery.EXTENSION_SUFFIXES:
                extension = location / f"{part}{suffix}"
                if extension.is_file():
                    sibling = _pyi_sibling(extension)
                    return sibling if sibling.is_file() else None
        return None
    return None


def _pyi_path_for_module(module_name: str) -> Path | None:
    """Locates the `.pyi` stub sibling of a compiled module's file.

    Some native extension modules (e.g. PyO3-built submodules) hijack
    `sys.modules` for themselves *and* their ancestor packages once
    actually imported, so `find_spec` can fail not just on the leaf module
    but several levels up too - confirmed empirically for
    `quri_parts.rust.circuit.circuit` (a real compiled module with a real
    `.pyi` stub on disk), where both it and its immediate parent
    `quri_parts.rust.circuit` report `__spec__ is None` once imported, but
    the grandparent `quri_parts.rust` still resolves normally. Walk up to
    the nearest ancestor that's still resolvable (worst case, the top-level
    package) and reconstruct the path for the remaining dotted segments
    underneath it, since the `.pyi` stub still lives on disk at that path
    even though the compiled module itself isn't independently locatable at
    runtime.
    """
    filesystem_stub = _pyi_path_on_sys_path(module_name)
    if filesystem_stub is not None:
        return filesystem_stub

    for _candidate, spec, remaining in _walk_resolvable_prefixes(module_name):
        if not remaining:
            return _pyi_sibling(Path(spec.origin)) if spec.origin else None

        if not spec.submodule_search_locations:
            continue
        *subdirs, leaf = remaining
        for search_location in spec.submodule_search_locations:
            candidate_path = Path(search_location).joinpath(*subdirs) / f"{leaf}.pyi"
            if candidate_path.exists():
                return candidate_path
            package_path = (
                Path(search_location).joinpath(*subdirs, leaf) / "__init__.pyi"
            )
            if package_path.exists():
                return package_path
    return None


def _pyi_lookup_target(
    obj, fallback_module_name: str, fallback_attrs: list[str]
) -> tuple[str, list[str]]:
    """Determines (module_name, attrs) to use for a `.pyi` lookup.

    Prefers the live object's own `__module__`/`__qualname__` over the
    dotted symbol's public import path: a symbol can be re-exported from a
    different module than the one it's actually defined in (e.g.
    `quri_parts.circuit.QuantumCircuit` is actually defined - and stubbed -
    in `quri_parts.rust.circuit.circuit`), so the stub lives next to the
    defining module, not necessarily the one the symbol was imported through.
    """
    module_name = getattr(obj, "__module__", None) if obj is not None else None
    qualname = getattr(obj, "__qualname__", None) if obj is not None else None
    if module_name and qualname:
        return module_name, qualname.split(".")
    return fallback_module_name, fallback_attrs


def _pyi_docstring(module_name: str, remaining_attrs: list[str]) -> str | None:
    """Backfills a docstring from the `.pyi` stub sibling to a compiled
    module, for an object that imported successfully but didn't carry one
    live (common for compiled extension classes that don't embed one).

    Only ever called with the object's own defining module/qualname (see
    `_pyi_lookup_target`), so there's no re-export to follow here - by
    definition, the stub at the true defining location declares the symbol
    directly, never as an import of it from somewhere else.
    """
    pyi_path = _pyi_path_for_module(module_name)
    if pyi_path is None or not pyi_path.exists():
        return None

    tree = ast.parse(pyi_path.read_text())
    if not remaining_attrs:
        return ast.get_docstring(tree, clean=True)

    node = _find_ast_node(tree.body, remaining_attrs)
    if node is None:
        return None
    return ast.get_docstring(node, clean=True)


def introspect_symbol(symbol: str, availability_symbols: list[str] | None = None) -> dict:
    """Introspects `symbol` in the current interpreter. Never raises."""
    result = {
        "symbol": symbol,
        "module": None,
        "qualname": None,
        "signature": None,
        "docstring": None,
        "source_file": None,
        "source_line": None,
        "source_text": None,
        "kind": None,
        "source": None,
        "error": None,
        "plus_namespaces": _check_plus_namespaces(),
        "plus_symbols": _check_symbols(availability_symbols or []),
    }
    try:
        module_name, remaining_attrs = _resolve_module_path(symbol)
        result["module"] = module_name
        result["qualname"] = ".".join(remaining_attrs) or module_name.rsplit(".", 1)[-1]

        try:
            obj = _live_object(module_name, remaining_attrs)
        except Exception as e:
            # Import failed outright - a trusted, licensed install is
            # expected to import cleanly, so this means the package is
            # genuinely missing or unlicensed. Reported plainly rather than
            # falling back to a .pyi stub for a full result.
            result["error"] = f"{type(e).__name__}: {e}"
            return result

        result.update(_inspect_live(obj))
        result["source"] = "inspect"
        # A real signature doesn't guarantee a docstring (e.g. a PyO3/Rust
        # class whose docstring isn't embedded) - a sibling .pyi stub can
        # still fill that gap.
        if not result["docstring"]:
            pyi_module, pyi_attrs = _pyi_lookup_target(obj, module_name, remaining_attrs)
            result["docstring"] = _pyi_docstring(pyi_module, pyi_attrs)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def main() -> None:
    symbol = sys.argv[1]
    print(json.dumps(introspect_symbol(symbol, sys.argv[2:])))


if __name__ == "__main__":
    main()
