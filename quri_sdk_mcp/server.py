from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import HttpResource
from fetch_tools import tool_from_resource
from markdown_resources import all_markdown_resources
from python_source_code_resources import all_python_source_code_resources
from text_resources import all_text_resources
from fetch import Fetcher, FetchRequestArgs, FetchResponse
from typing import Optional


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
        """Fetch a website, convert its HTML content to Markdown, and return
        it. This tool should be used to fetch tutorials and example codes from
        the quri-sdk documentation site. Use this when the user requests to see
        a tutorial or example code, or use it when you need to learn how to do
        something using one of the tutorials or examples.

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
    async def fetch_raw_python(
        url: str, headers: Optional[dict[str, str]] = None
    ) -> FetchResponse:
        """This function should be used to fetch files directly from the quri-
        sdk repository. Use this to fetch python source code when needed. If
        you are unsure what to fetch, try first fetching the repository file-
        tree using one of the other tools.

        Args:
            url (str): URL of the website to fetch.
            headers (Optional[dict[str, str]]): Custom headers for the request.

        Returns:
            FetchResponse: An object containing the requested content or an error message.
                        On success, isError is false and content contains the Markdown text.
                        On failure, isError is true and errorMessage contains the error details.
        """

        args = FetchRequestArgs(url=url, headers=headers)
        return await Fetcher.txt(args)

    @mcp.tool()
    async def fetch_raw_python_notebook(
        url: str, headers: Optional[dict[str, str]] = None
    ) -> FetchResponse:
        """This function should be used to fetch files directly from the quri-
        sdk repository. Use this to fetch python notebooks when needed. If you
        are unsure what to fetch, try first fetching the repository file-tree
        using one of the other tools.

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

    return mcp


if __name__ == "__main__":
    mcp = get_mcp_server()
    mcp.run(transport="stdio")
