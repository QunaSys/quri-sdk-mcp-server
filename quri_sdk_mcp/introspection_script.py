"""Stdlib-only introspection script, run inside the *target* interpreter.

Invoked as `python introspection_script.py <dotted.symbol>` by
`quri_sdk_mcp.introspection.lookup_symbol` via subprocess, so it must not
import anything beyond the standard library - it runs inside the user's own
project interpreter, not this server's.

Resolution order for a symbol's signature/docstring:
1. Live `inspect.signature()`/`inspect.getdoc()`. This resolves for OSS
   packages and for internal dev/editable `.plus` installs, since both are
   plain `.py` source.
2. If live introspection yields no usable signature at all (a Cython-
   compiled `.plus` customer wheel built without `embedsignature`), fall
   back entirely to the sibling `.pyi` stub for both signature and
   docstring. If it yields a signature but no docstring (common for
   compiled extension classes - e.g. quri-parts' Rust/PyO3 circuit types -
   that don't embed one), backfill just the docstring from the `.pyi`
   instead of discarding the real signature.

   The `.pyi` lookup itself doesn't necessarily use the module the symbol
   was imported through: a symbol can be re-exported from a different
   module than the one it's actually defined in, so it's located from the
   live object's own `__module__`/`__qualname__` when available (see
   `_pyi_lookup_target`). Locating the stub is itself not always a plain
   `find_spec(module).origin` - some native extension modules (e.g. some
   PyO3-built submodules) hijack `sys.modules` for themselves and their
   ancestor packages once imported, so `find_spec` can fail several levels
   up; `_pyi_path_for_module` walks up to the nearest still-resolvable
   ancestor and reconstructs the path from there. None of this executes
   the target module, so it also works under license gating.

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
    """Reports whether each exact dotted symbol is present without importing it."""
    availability = {}
    for symbol in symbols:
        try:
            availability[symbol] = _symbol_exists_without_import(symbol)
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
    for node in body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name != target:
            continue
        if not rest:
            return node
        if isinstance(node, ast.ClassDef):
            return _find_ast_node(node.body, rest)
        return None
    return None


def _find_ast_declaration(body: list, names: list[str]):
    """Finds a callable, class, variable, or re-export declaration."""
    node = _find_ast_node(body, names)
    if node is not None or len(names) != 1:
        return node

    name = names[0]
    for candidate in body:
        if isinstance(candidate, (ast.Import, ast.ImportFrom)):
            if any(
                (alias.asname or alias.name.rsplit(".", 1)[-1]) == name
                for alias in candidate.names
            ):
                return candidate
        if isinstance(candidate, ast.AnnAssign):
            if isinstance(candidate.target, ast.Name) and candidate.target.id == name:
                return candidate
        if isinstance(candidate, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == name
                for target in candidate.targets
            ):
                return candidate
    return None


def _ast_defines_name(body: list, name: str) -> bool:
    """Whether a module AST defines or re-exports `name`."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name.rsplit(".", 1)[-1]) == name for alias in node.names):
                return True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                return True
    return False


def _pyi_sibling(module_path: Path) -> Path:
    """Returns the stub path for a Python or ABI-suffixed extension module."""
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        if module_path.name.endswith(suffix):
            stem = module_path.name[: -len(suffix)]
            return module_path.with_name(f"{stem}.pyi")
    return module_path.with_suffix(".pyi")


def _declaration_defines_attrs(path: Path, attrs: list[str]) -> bool:
    """Checks declarations in a source or stub file without importing it."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    if len(attrs) == 1:
        return _ast_defines_name(tree.body, attrs[0])
    return _find_ast_node(tree.body, attrs) is not None


def _symbol_exists_on_sys_path(symbol: str) -> bool:
    """Resolves an installed symbol from package files without imports.

    `find_spec("package.compiled.child")` imports `package.compiled` while
    locating the child. Enterprise package initializers are native extensions
    and can enforce licensing at import time, so availability detection must
    walk their installed directories and sibling stubs directly instead.
    """
    parts = symbol.split(".")
    locations = [Path(entry) for entry in sys.path if entry and Path(entry).is_dir()]
    module_suffixes = [".pyi", ".py", *importlib.machinery.EXTENSION_SUFFIXES]

    for index, part in enumerate(parts):
        package_dirs = [location / part for location in locations]
        package_dirs = [path for path in package_dirs if path.is_dir()]
        remaining = parts[index + 1 :]
        if package_dirs:
            if not remaining:
                return True
            locations = package_dirs
            continue

        module_files = [
            location / f"{part}{suffix}"
            for location in locations
            for suffix in module_suffixes
            if (location / f"{part}{suffix}").is_file()
        ]
        if module_files:
            if not remaining:
                return True
            declaration_files = []
            for module_file in module_files:
                if module_file.suffix in (".py", ".pyi"):
                    declaration_files.append(module_file)
                else:
                    declaration_files.append(_pyi_sibling(module_file))
            return any(
                path.is_file() and _declaration_defines_attrs(path, remaining)
                for path in declaration_files
            )

        declaration_files = [
            package_dir / filename
            for package_dir in locations
            for filename in ("__init__.pyi", "__init__.py")
        ]
        return any(
            path.is_file() and _declaration_defines_attrs(path, parts[index:])
            for path in declaration_files
        )
    return False


def _symbol_exists_without_import(symbol: str) -> bool:
    """Checks a mapped symbol's module and declaration without import side effects."""
    if _symbol_exists_on_sys_path(symbol):
        return True
    if any(
        symbol == namespace or symbol.startswith(f"{namespace}.")
        for namespace in PLUS_NAMESPACES
    ):
        return False

    parts = symbol.split(".")
    for index in range(1, len(parts) + 1):
        module_name = ".".join(parts[:index])
        try:
            spec = importlib.util.find_spec(module_name)
        except Exception:
            return False
        if spec is None:
            return False
        remaining_attrs = parts[index:]
        if not remaining_attrs:
            return True
        if len(remaining_attrs) == 1 and spec.origin:
            source_path = Path(spec.origin)
            candidates = [source_path]
            if source_path.suffix != ".pyi":
                candidates.append(_pyi_sibling(source_path))
            for candidate in candidates:
                if candidate.suffix not in (".py", ".pyi") or not candidate.exists():
                    continue
                tree = ast.parse(candidate.read_text())
                if _ast_defines_name(tree.body, remaining_attrs[0]):
                    return True
        if not spec.submodule_search_locations:
            return False
    return False


def _signature_from_pyi_node(node) -> str | None:
    if isinstance(node, ast.ClassDef):
        constructor = _find_ast_node(node.body, ["__init__"])
        if constructor is None:
            constructor = _find_ast_node(node.body, ["__new__"])
        if constructor is None:
            return None

        args = constructor.args
        posonlyargs = list(args.posonlyargs)
        positional_args = list(args.args)
        if posonlyargs:
            posonlyargs.pop(0)
        elif positional_args:
            positional_args.pop(0)
        constructor_args = ast.arguments(
            posonlyargs=posonlyargs,
            args=positional_args,
            vararg=args.vararg,
            kwonlyargs=args.kwonlyargs,
            kw_defaults=args.kw_defaults,
            kwarg=args.kwarg,
            defaults=args.defaults,
        )
        return f"({ast.unparse(constructor_args)})"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"


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


def _pyi_stub_lookup(module_name: str, remaining_attrs: list[str]) -> dict | None:
    """Parses the `.pyi` stub sibling to a compiled module for a symbol."""
    pyi_path = _pyi_path_for_module(module_name)
    if pyi_path is None or not pyi_path.exists():
        return None

    tree = ast.parse(pyi_path.read_text())
    if not remaining_attrs:
        return {
            "signature": None,
            "docstring": ast.get_docstring(tree, clean=True),
            "source_file": str(pyi_path),
            "source_line": None,
            "source_text": None,
            "kind": "module",
        }

    node = _find_ast_declaration(tree.body, remaining_attrs)
    if node is None:
        return None

    if isinstance(node, ast.ImportFrom) and len(remaining_attrs) == 1:
        public_name = remaining_attrs[0]
        alias = next(
            (
                alias
                for alias in node.names
                if (alias.asname or alias.name.rsplit(".", 1)[-1]) == public_name
            ),
            None,
        )
        if alias is not None and node.module:
            if node.level:
                package_name = (
                    module_name
                    if pyi_path.name == "__init__.pyi"
                    else module_name.rsplit(".", 1)[0]
                )
                target_module = importlib.util.resolve_name(
                    f"{'.' * node.level}{node.module}", package_name
                )
            else:
                target_module = node.module
            target = _pyi_stub_lookup(target_module, [alias.name])
            if target is not None:
                return target

    if isinstance(node, ast.ClassDef):
        kind = "class"
        signature = _signature_from_pyi_node(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kind = "function"
        signature = _signature_from_pyi_node(node)
    else:
        kind = "variable"
        signature = ast.unparse(node)
    return {
        "signature": signature,
        "docstring": (
            ast.get_docstring(node, clean=True)
            if isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            )
            else None
        ),
        "source_file": str(pyi_path),
        "source_line": node.lineno,
        # No real Python body to return for compiled code, a .pyi stub only
        # has declarations, not the implementation.
        "source_text": None,
        "kind": kind,
    }


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

        live_error = None
        live = None
        obj = None
        try:
            obj = _live_object(module_name, remaining_attrs)
            live = _inspect_live(obj)
        except Exception as e:
            live_error = f"{type(e).__name__}: {e}"

        pyi_module, pyi_attrs = _pyi_lookup_target(obj, module_name, remaining_attrs)

        if live is not None and live["signature"] is not None:
            result.update(live)
            result["source"] = "inspect"
            # Live inspect got a real signature but not necessarily a
            # docstring (e.g. a PyO3/Rust class whose docstring isn't
            # embedded) - a sibling .pyi stub can still fill that gap.
            if not result["docstring"]:
                stub = _pyi_stub_lookup(pyi_module, pyi_attrs)
                if stub and stub.get("docstring"):
                    result["docstring"] = stub["docstring"]
        else:
            stub = _pyi_stub_lookup(pyi_module, pyi_attrs)
            if stub is not None:
                result.update(stub)
                result["source"] = "pyi_stub"
            elif live is not None:
                result.update(live)
                result["source"] = "inspect"
            elif live_error is not None:
                result["error"] = live_error
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def main() -> None:
    symbol = sys.argv[1]
    print(json.dumps(introspect_symbol(symbol, sys.argv[2:])))


if __name__ == "__main__":
    main()
