import json
import subprocess
import sys

import httpx
from mcp.server.fastmcp.resources.types import HttpResource

from quri_sdk_mcp.env_resolution import (
    get_versions,
    resolve_doc_ref,
    resolve_target_python,
)
from quri_sdk_mcp.fetch import Fetcher, FetchRequestArgs

try:
    _doc_ref = resolve_doc_ref(get_versions(resolve_target_python()))
except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as e:
    print(
        f"quri-sdk-mcp: failed to resolve target Python's package versions, "
        f"falling back to 'main': {e}",
        file=sys.stderr,
    )
    _doc_ref = "main"

_quri_algo_algorithm_base = HttpResource(
    uri="qsdk://source/algo/algorithms/base",
    url="https://raw.githubusercontent.com/QunaSys/quri-sdk/refs/heads/main/quri-algo/quri_algo/algo/interface.py",
    mime_type="text/x-python",
    name="quri_algo_algorithm_base",
    title="Base classes and definitions for algorithms",
    description="""This python source file details the interface for quri-algo style Algorithms. Algorithms written for quri-algo should follow this style.
""",
)

_MAIN_TREE_URL = "https://api.github.com/repos/QunaSys/quri-sdk/git/trees/main?recursive=1"


class _SourceTreeResource(HttpResource):
    """HttpResource for the quri-sdk tree, falling back to `main` if `_doc_ref`
    (e.g. an editable/dev version string) isn't an actual git ref. Reads go
    through Fetcher so this GitHub API host gets the same GITHUB_TOKEN auth
    and response caching as every other GitHub call (fetcher.py)."""

    async def read(self) -> str | bytes:
        try:
            response = await Fetcher._fetch(FetchRequestArgs(url=self.url))
            return response.text
        except ConnectionError as e:
            cause = e.__cause__
            is_404 = isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 404
            if is_404 and self.url != _MAIN_TREE_URL:
                response = await Fetcher._fetch(FetchRequestArgs(url=_MAIN_TREE_URL))
                return response.text
            raise


_quri_sdk_source_file_tree = _SourceTreeResource(
    uri="qsdk://source/tree",
    url=f"https://api.github.com/repos/QunaSys/quri-sdk/git/trees/{_doc_ref}?recursive=1",
    mime_type="application/json",
    name="quri_sdk_source_code_tree",
    title="Source code tree for quri-sdk codebase",
    description=f"""This resource provides the source code tree for quri-sdk at ref `{_doc_ref}`.

    Using the information here you can get an overview of the code-base structure and source files to fetch and analyse.""",
)

all_python_source_code_resources = (
    _quri_algo_algorithm_base,
    _quri_sdk_source_file_tree,
)
