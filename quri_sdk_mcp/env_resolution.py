"""Version and target-interpreter resolution for the quri-sdk-mcp server.

Introspection and corpus building need to know which Python interpreter the
user's project actually uses, and which quri-sdk-family versions are
installed there, since `quri-sdk` itself is an empty meta-package (real code
lives in separately-versioned `quri_parts`/`quri_algo`/`quri_vm`).
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

TRACKED_PACKAGES = ("quri-sdk", "quri-parts", "quri-algo", "quri-vm")


def resolve_target_python() -> Path:
    """Resolves the Python interpreter to introspect.

    Returns:
        The interpreter from the `QURI_SDK_MCP_PYTHON` env var if set, else
        this server's own interpreter.
    """
    override = os.environ.get("QURI_SDK_MCP_PYTHON")
    if override:
        return Path(override)
    return Path(sys.executable)


_VERSION_SCRIPT = """
import importlib.metadata, json
names = {names!r}
out = {{}}
for name in names:
    try:
        out[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        out[name] = None
print(json.dumps(out))
"""


def get_versions(python: Path) -> dict[str, str | None]:
    """Resolves installed versions of the quri-sdk-family packages.

    Args:
        python: Interpreter to resolve versions in.

    Returns:
        Mapping of package name to installed version, or None if not
        installed.
    """
    if python == Path(sys.executable):
        versions: dict[str, str | None] = {}
        for name in TRACKED_PACKAGES:
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = None
        return versions

    script = _VERSION_SCRIPT.format(names=TRACKED_PACKAGES)
    result = subprocess.run(
        [str(python), "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def resolve_doc_ref(versions: dict[str, str | None]) -> str:
    """Picks the value to use for per-version corpus lookup/introspection.

    Args:
        versions: Output of `get_versions`.

    Returns:
        The `quri-parts` version if resolved (since `quri-sdk` itself is
        meaningless), else `"main"`.
    """
    quri_parts_version = versions.get("quri-parts")
    if quri_parts_version:
        return quri_parts_version
    return "main"


def get_editable_source(
    python: Path, package: str = "quri-parts"
) -> Path | None:
    """Checks whether a package is installed editable (`pip install -e .`).

    Args:
        python: Interpreter to check.
        package: Distribution name to check.

    Returns:
        The local source path if the distribution is an editable, local
        install, else None.
    """
    if python == Path(sys.executable):
        try:
            dist = importlib.metadata.Distribution.from_name(package)
        except importlib.metadata.PackageNotFoundError:
            return None
        direct_url_text = dist.read_text("direct_url.json")
    else:
        script = (
            "import importlib.metadata, sys\n"
            "try:\n"
            "    dist = importlib.metadata.Distribution.from_name(\n"
            f"        {package!r})\n"
            "except importlib.metadata.PackageNotFoundError:\n"
            "    sys.exit(0)\n"
            "text = dist.read_text('direct_url.json')\n"
            "if text is not None:\n"
            "    print(text)\n"
        )
        result = subprocess.run(
            [str(python), "-c", script],
            capture_output=True,
            text=True,
            check=True,
        )
        direct_url_text = result.stdout or None

    if not direct_url_text:
        return None

    direct_url = json.loads(direct_url_text)
    is_editable = direct_url.get("dir_info", {}).get("editable", False)
    url = direct_url.get("url", "")
    if is_editable and url.startswith("file://"):
        return Path(url2pathname(urlparse(url).path))
    return None
