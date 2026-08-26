"""Stdlib-only introspection script, run inside the *target* interpreter.

Invoked as `python introspection_script.py <dotted.symbol>` by
`quri_sdk_mcp.introspection.lookup_symbol` via subprocess, so it must not
import anything beyond the standard library - it runs inside the user's own
project interpreter, not this server's.

Resolution order for a symbol's signature/docstring:
1. Live `inspect.signature()`/`inspect.getdoc()`. This resolves for OSS
   packages and for internal dev/editable `.plus` installs, since both are
   plain `.py` source.
2. If live introspection yields no usable signature (a Cython-compiled
   `.plus` customer wheel built without `embedsignature`), fall back to the
   sibling `.pyi` stub next to the compiled module, located via
   `importlib.util.find_spec(module).origin` (this does not execute the
   module, so it also works under license gating) and parsed with `ast`.

Always prints one JSON object and exits 0, even on failure, so the caller
can treat "symbol not found" as data rather than a subprocess error.
"""

import ast
import importlib
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


def _resolve_module_path(dotted: str) -> tuple[str, list[str]]:
    """Splits a dotted symbol into its module path and remaining attributes.

    Tries the longest prefix of `dotted` that resolves to a locatable module
    via `find_spec`, without executing it, so this also works for compiled
    modules under license gating that would raise on live import.

    Returns:
        (module_name, remaining_attrs) - remaining_attrs is empty if `dotted`
        names a module itself.
    """
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        try:
            spec = importlib.util.find_spec(candidate)
        except Exception:
            spec = None
        if spec is not None:
            return candidate, parts[i:]
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

    return {
        "signature": signature,
        "docstring": inspect.getdoc(obj),
        "source_file": source_file,
        "source_line": source_line,
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


def _signature_from_pyi_node(node) -> str | None:
    if isinstance(node, ast.ClassDef):
        return None
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"


def _pyi_stub_lookup(module_name: str, remaining_attrs: list[str]) -> dict | None:
    """Parses the `.pyi` stub sibling to a compiled module for a symbol."""
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        spec = None
    if spec is None or spec.origin is None:
        return None

    pyi_path = Path(spec.origin).with_suffix(".pyi")
    if not pyi_path.exists():
        return None

    tree = ast.parse(pyi_path.read_text())
    if not remaining_attrs:
        return {
            "signature": None,
            "docstring": ast.get_docstring(tree, clean=True),
            "source_file": str(pyi_path),
            "source_line": None,
            "kind": "module",
        }

    node = _find_ast_node(tree.body, remaining_attrs)
    if node is None:
        return None

    kind = "class" if isinstance(node, ast.ClassDef) else "function"
    return {
        "signature": _signature_from_pyi_node(node),
        "docstring": ast.get_docstring(node, clean=True),
        "source_file": str(pyi_path),
        "source_line": node.lineno,
        "kind": kind,
    }


def introspect_symbol(symbol: str) -> dict:
    """Introspects `symbol` in the current interpreter. Never raises."""
    result = {
        "symbol": symbol,
        "module": None,
        "qualname": None,
        "signature": None,
        "docstring": None,
        "source_file": None,
        "source_line": None,
        "kind": None,
        "source": None,
        "error": None,
        "plus_namespaces": _check_plus_namespaces(),
    }
    try:
        module_name, remaining_attrs = _resolve_module_path(symbol)
        result["module"] = module_name
        result["qualname"] = ".".join(remaining_attrs) or module_name.rsplit(".", 1)[-1]

        live_error = None
        live = None
        try:
            obj = _live_object(module_name, remaining_attrs)
            live = _inspect_live(obj)
        except Exception as e:
            live_error = f"{type(e).__name__}: {e}"

        if live is not None and live["signature"] is not None:
            result.update(live)
            result["source"] = "inspect"
        else:
            stub = _pyi_stub_lookup(module_name, remaining_attrs)
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
    print(json.dumps(introspect_symbol(symbol)))


if __name__ == "__main__":
    main()
