import asyncio

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import HttpResource
from quri_sdk_mcp.fetch_tools import tool_from_resource
from quri_sdk_mcp.markdown_resources import all_markdown_resources
from quri_sdk_mcp.python_source_code_resources import all_python_source_code_resources
from quri_sdk_mcp.text_resources import all_text_resources
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
        notebooks! This function creates a virtual environment for code evaluation. It
        first checks that the code would run. Then it checks that the typing
        information provided makes sense. It then optionally runs the code.

        Args:
            code (str): The python code in a single string.
            dependencies: Additional dependencies to include in the virtual environment besides quri-sdk
            execuyte_code_after_check: Whether to execute the code directly in the virtual environment to see if it runs according to expectations
        """
        if dependencies is None:
            dependencies = []
        if not "quri_sdk" in dependencies:
            dependencies.append("quri_sdk")

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

    return mcp


if __name__ == "__main__":
    mcp = get_mcp_server()
    mcp.run(transport="stdio")
