from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import HttpResource
from fetch_tools import all_fetch_tools
from prompts import quri_sdk_docs_toc_prompt
from http_resources import all_http_resources
from fetch import Fetcher, FetchRequestArgs, FetchResponse
from typing import Optional


def get_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "QURI SDK code assistance platform",
        instructions="""This server provides tools to assist with code generation for quantum computing using QURI SDK

    ## Core Features
    - Abstraction layer for quantum circuits and operators with QURI Parts
    - Quantum circuit simulation using QURI Parts Qulacs
    - Quantum circuit synthesis using QURI Parts QSub module
    - Quantum algorithm deployment using QURI Algo
    - Quantum resource estimation using QURI VM

    """,
    )

    # for uri, t in all_fetch_tools.items():
    #     mcp.resource(uri)(t)
    for t in all_fetch_tools:
        mcp.add_tool(t)

    for r in all_http_resources:
        mcp.add_resource(r)

    # Utils ----------------------
    @mcp.tool()
    async def fetch_as_markdown(
        url: str, headers: Optional[dict[str, str]] = None
    ) -> FetchResponse:
        """
        Fetch a website, convert its HTML content to Markdown, and return it.

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

    return mcp


if __name__ == "__main__":
    mcp = get_mcp_server()
    mcp.run(transport="stdio")
