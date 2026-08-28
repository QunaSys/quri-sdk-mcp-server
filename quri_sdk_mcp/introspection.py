"""`lookup_api` implementation: subprocess introspection + `.plus` mapping."""

from __future__ import annotations

import importlib.resources
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from quri_sdk_mcp.env_resolution import resolve_target_python

_INTROSPECTION_SCRIPT = Path(__file__).parent / "introspection_script.py"


def load_plus_mapping() -> dict[str, list[dict[str, Any]]]:
    """Loads the curated OSS-symbol -> `.plus`-equivalent mapping.

    A single OSS symbol can have more than one `.plus` upgrade (e.g. a VM
    backend with both a Braket and a Qiskit variant), so entries are grouped
    into lists rather than overwriting one another.

    Returns:
        Mapping keyed by OSS symbol (dotted path) to its list of known
        `.plus` upgrades.
    """
    text = (
        importlib.resources.files("quri_sdk_mcp.data")
        .joinpath("plus_mapping.json")
        .read_text()
    )
    entries = json.loads(text)
    by_oss_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        if entry["oss_symbol"] is not None:
            by_oss_symbol[entry["oss_symbol"]].append(entry)
    return dict(by_oss_symbol)


def lookup_symbol(symbol: str) -> dict[str, Any]:
    """Looks up a `quri_parts`/`quri_algo`/`quri_vm` symbol in the target
    interpreter (see `env_resolution.resolve_target_python`).

    Args:
        symbol: Fully dotted symbol path, e.g.
            "quri_parts.circuit.QuantumCircuit".

    Returns:
        Introspection result (signature, docstring, source location and
        text). If one or more `.plus` upgrades are known for this symbol,
        includes a `plus_equivalents` list, each entry annotated with
        `available` (whether the target interpreter actually has that
        `.plus` namespace installed).
    """
    python = resolve_target_python()
    try:
        process = subprocess.run(
            [str(python), str(_INTROSPECTION_SCRIPT), symbol],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(process.stdout)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as e:
        return {
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
            "error": f"Failed to introspect via {python}: {e}",
            "plus_namespaces": {},
        }

    plus_entries = load_plus_mapping().get(symbol)
    if plus_entries:
        installed_namespaces = info.get("plus_namespaces", {})
        info["plus_equivalents"] = [
            {**entry, "available": installed_namespaces.get(entry["plus_namespace"], False)}
            for entry in plus_entries
        ]
    return info
