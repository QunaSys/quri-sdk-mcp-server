import asyncio

from mcp.server.fastmcp import FastMCP
from quri_sdk_mcp.fetch_tools import tool_from_resource
from quri_sdk_mcp.markdown_resources import all_markdown_resources
from quri_sdk_mcp.python_source_code_resources import all_python_source_code_resources
from quri_sdk_mcp.text_resources import all_text_resources
from quri_sdk_mcp.corpus import (
    fetch_example_source as fetch_example_source_corpus,
    search as search_docs_corpus,
)
from quri_sdk_mcp.fetch import FetchResponse
from quri_sdk_mcp.introspection import lookup_symbol
from quri_sdk_mcp.py_checker import run_code_in_temporary_venv, timeout_result
from typing import Optional, Any


def get_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "QURI SDK code assistance platform",
        instructions="""#This server provides tools to assist with code generation for quantum computing using QURI SDK

    ## Core features of QURI SDK
    - Abstraction layer for quantum circuits and operators with QURI Parts
    - Quantum circuit simulation using QURI Parts Qulacs
    - Quantum circuit synthesis using QURI Parts QSub module
    - Quantum algorithm deployment using QURI Algo
    - Quantum resource estimation using QURI VM

    ## Tools
    - Tools are provided that fetch documentation
    - Tools are provided that fetch base classes and source code
    - Tools are provided that fetch example use cases

    """,
    )

    for r in all_text_resources:
        mcp.add_resource(r)
        mcp.add_tool(tool_from_resource(r))

    for r in all_markdown_resources:
        mcp.add_resource(r)
        mcp.add_tool(tool_from_resource(r))

    for r in all_python_source_code_resources:
        mcp.add_resource(r)
        mcp.add_tool(tool_from_resource(r))

    # Utils ----------------------
    @mcp.tool()
    async def fetch_example_source(
        path: str, working_directory: Optional[str] = None
    ) -> FetchResponse:
        """Fetches the exact runnable source behind a `search_docs`/
        `get_example` result. Use this once `get_example` has found the
        right tutorial or how-to and you need the precise, cell-accurate
        code to run or adapt - the rendered/searched text loses things like
        exact cell boundaries and image outputs that the raw notebook keeps.

        Args:
            path (str): The `path` field from a `search_docs`/`get_example`
                match, e.g. "docs/tutorials/quri-parts/circuits".
            working_directory (Optional[str]): The `working_directory` field
                returned with a local search result. Omit for remote results.

        Returns:
            FetchResponse: the raw notebook (`.ipynb` JSON), Markdown, or RST
                source, or an error if none exists at that path.
        """
        try:
            text = await fetch_example_source_corpus(path, working_directory)
            return FetchResponse(content=[{"type": "text", "text": text}], isError=False)
        except (ConnectionError, ValueError) as e:
            return FetchResponse(content=[], isError=True, errorMessage=str(e))

    @mcp.tool()
    async def check_code(
        code: str,
        dependencies: Optional[list[str]] = None,
        execute_code_after_check: Optional[bool] = None,
    ) -> dict[str, Any]:
        """This function should be used to check the code produced by a LLM. The code
        is passed directly as python executable string - note this does not support
        notebooks! This function creates a validation environment with the Python
        selected by QURI_SDK_MCP_PYTHON and exposes that interpreter's installed
        packages to Pyright and optional execution. Explicit additional dependencies
        are installed only in the cached validation environment.

        Args:
            code (str): The python code in a single string.
            dependencies: Additional dependencies to install in the validation environment.
            execute_code_after_check: Whether to execute the code directly in the validation environment to see if it runs according to expectations.
        """
        if dependencies is None:
            dependencies = []

        try:
            if execute_code_after_check is None:
                return await asyncio.to_thread(run_code_in_temporary_venv, code, dependencies)
            else:
                return await asyncio.to_thread(
                    run_code_in_temporary_venv, code, dependencies, execute_code_after_check
                )
        except TimeoutError as e:
            return timeout_result(str(e))

    @mcp.tool()
    async def lookup_api(symbol: str) -> dict[str, Any]:
        """Look up the actual signature, docstring, source location and
        source code for a quri_parts/quri_algo/quri_vm symbol as installed in
        the user's own project. This should be the first stop for any
        question about a QURI SDK API's exact arguments, types, usage, or
        implementation - prefer this over guessing or fetching from GitHub,
        since signatures vary by installed version and this introspects the
        interpreter the user's project actually uses (set via the
        QURI_SDK_MCP_PYTHON environment variable, falling back to this
        server's own interpreter), so `source_text` always matches what's
        actually installed. `source_text` is only available for symbols with
        a live Python implementation; it is None for compiled Enterprise
        wheels resolved via a `.pyi` stub, since there is no Python body to
        return.

        Also cross-references the symbol against known Enterprise `.plus`
        upgrades. When generating code, prefer a `.plus` equivalent listed in
        `plus_equivalents` if its `available` field is true.

        Args:
            symbol (str): Fully dotted symbol path, e.g.
                "quri_parts.circuit.QuantumCircuit" or
                "quri_parts.qulacs.sampler.create_qulacs_vector_sampler".

        Returns:
            dict: Introspection result with signature, docstring, source
                location, source text, and (if known) a plus_equivalents list.
        """
        return await asyncio.to_thread(lookup_symbol, symbol)

    @mcp.tool()
    async def search_docs(
        query: str,
        categories: Optional[list[str]] = None,
        limit: int = 10,
        working_directory: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """Searches QURI SDK documentation (tutorials, how-to guides,
        reference pages, and release notes) via lexical keyword search. This
        should be the first stop for finding relevant documentation - it
        searches the actual doc corpus instead of guessing a URL to fetch.

        Args:
            query (str): Free-text search terms, e.g. "qulacs sampler" or
                "parametric circuit gradient".
            categories (Optional[list[str]]): Restrict results to these
                categories: "tutorial", "how-to", "reference", "changelog",
                "concept". Omit to search all categories.
            limit (int): Max number of results.
            working_directory (Optional[str]): Absolute path to a local
                docs checkout (e.g. a quri-sdk or quri-sdk-enterprise
                checkout with a `docs/` directory) to search instead of the
                cached live-site corpus. Pass this if the current project
                root itself looks like such a checkout (a `docs/` directory
                next to a pyproject.toml naming
                quri-parts/quri-algo/quri-vm/quri-sdk-enterprise), so
                results match the exact branch being worked on instead of
                the deployed site. Local results include this path in their
                `working_directory` field for `fetch_example_source`. Usually
                not needed - this is
                auto-detected from the target interpreter's editable-install
                metadata when possible, searching both quri-parts and
                quri-sdk-enterprise checkouts together if both are found.

        Returns:
            list[dict]: Matches as {path, category, title, snippet}, best
                match first. Local matches also include working_directory.
        """
        return await search_docs_corpus(
            query, categories=categories, limit=limit, working_directory=working_directory
        )

    @mcp.tool()
    async def get_example(
        query: str,
        limit: int = 5,
        working_directory: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """Finds a QURI SDK tutorial or how-to guide matching `query`. This
        is the tool to reach for when the user asks to see an example or how
        to do something - it's `search_docs` pre-restricted to tutorial and
        how-to content.

        Args:
            query (str): Free-text search terms, e.g. "qulacs sampler" or
                "parametric circuit gradient".
            limit (int): Max number of results.
            working_directory (Optional[str]): See `search_docs`.

        Returns:
            list[dict]: Matches as {path, category, title, snippet}, best
                match first.
        """
        return await search_docs_corpus(
            query,
            categories=["tutorial", "how-to"],
            limit=limit,
            working_directory=working_directory,
        )

    return mcp


def main() -> None:
    mcp = get_mcp_server()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
