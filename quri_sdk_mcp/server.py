import asyncio

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import HttpResource
from quri_sdk_mcp.fetch_tools import tool_from_resource
from quri_sdk_mcp.markdown_resources import all_markdown_resources
from quri_sdk_mcp.python_source_code_resources import all_python_source_code_resources
from quri_sdk_mcp.text_resources import all_text_resources
from quri_sdk_mcp.corpus import search as search_docs_corpus
from quri_sdk_mcp.fetch import Fetcher, FetchRequestArgs, FetchResponse
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
    async def fetch_as_markdown(
        url: str, headers: Optional[dict[str, str]] = None
    ) -> FetchResponse:
        """Fetch a website, convert its HTML content to Markdown, and return it. This
        tool should be used to fetch tutorials and example codes from the quri-sdk
        documentation site. Use this when the user requests to see a tutorial or example
        code, or use it when you need to learn how to do something using one of the
        tutorials or examples.

        Args:
            url (str): URL of the website to fetch.
            headers (Optional[dict[str, str]]): Custom headers for the request.

        Returns:
            FetchResponse: An object containing the Markdown content or an error message.
                        On success, isError is false and content contains the Markdown text.
                        On failure, isError is true and errorMessage contains the error details.
        """
        args = FetchRequestArgs(url=url, headers=headers)
        return await Fetcher.markdown(args)

    @mcp.tool()
    async def fetch_raw_python_notebook(
        url: str, headers: Optional[dict[str, str]] = None
    ) -> FetchResponse:
        """This function should be used to fetch files directly from the quri- sdk
        repository. Use this to fetch python notebooks when needed. If you are unsure
        what to fetch, try first fetching the repository file-tree using one of the
        other tools.

        Args:
            url (str): URL of the website to fetch.
            headers (Optional[dict[str, str]]): Custom headers for the request.

        Returns:
            FetchResponse: An object containing the requested content or an error message.
                        On success, isError is false and content contains the Markdown text.
                        On failure, isError is true and errorMessage contains the error details.
        """

        args = FetchRequestArgs(url=url, headers=headers)
        return await Fetcher.json(args)

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
        """Searches QURI SDK documentation (tutorials, examples, community
        docs, and release notes) via lexical keyword search. This should be
        the first stop for finding relevant documentation - it searches the
        actual per-version doc corpus instead of guessing a URL to fetch.

        Args:
            query (str): Free-text search terms, e.g. "qulacs sampler" or
                "parametric circuit gradient".
            categories (Optional[list[str]]): Restrict results to these
                categories: "tutorial", "how-to", "reference", "changelog",
                "concept". Omit to search all categories.
            limit (int): Max number of results.
            working_directory (Optional[str]): Absolute path to a local
                quri-sdk-docusaurus (or quri-sdk-enterprise) checkout to
                search instead of the cached released-version corpus. Pass
                this if the current project root itself looks like such a
                checkout (a `docs/` directory next to a pyproject.toml
                naming quri-parts/quri-algo/quri-vm/quri-sdk-enterprise), so
                results match the exact branch being worked on instead of
                the last resolved release. Usually not needed - this is
                auto-detected from the target interpreter's editable-install
                metadata when possible.

        Returns:
            list[dict]: Matches as {path, category, title, snippet}, best
                match first.
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


if __name__ == "__main__":
    mcp = get_mcp_server()
    mcp.run(transport="stdio")
