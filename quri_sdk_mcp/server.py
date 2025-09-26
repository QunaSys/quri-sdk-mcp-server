from mcp.server.fastmcp import FastMCP
from prompts import quri_sdk_tutorial_prompt
from fetch import Fetcher, FetchRequestArgs, FetchResponse
from typing import Optional

mcp = FastMCP(
    "QURI SDK code assistance platform",
    instructions="""This server provides tools to assist with code generation for quantum computing using QURI SDK

## Core Features
- Abstraction layer for quantum circuits and operators with QURI Parts
- Quantum circuit simulation using QURI Parts Qulacs
- Quantum circuit synthesis using QURI Parts QSub module
- Quantum algorithm deployment using QURI Algo
- Quantum resource estimation using QURI VM

"""
)
@mcp.resource("https://quri-sdk.qunasys.com/docs/tutorials")
def quri_sdk_tutorial() -> str:
    """
    Provide a guide to quri-sdk

    Returns:
        str: The guide to quri-sdk
    """

    return quri_sdk_tutorial_prompt


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


if __name__ == "__main__":
    mcp.run(transport="stdio")
