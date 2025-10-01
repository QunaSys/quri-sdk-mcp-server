from typing import Callable

from prompts import quri_sdk_docs_toc_prompt
from http_resources import all_http_resources
from mcp.server.fastmcp.resources import Resource

def _quri_sdk_docs_toc() -> str:
    """
    Provide TOC for quri-sdk documentation

    Returns:
        str: The TOC and usage guide
    """

    return quri_sdk_docs_toc_prompt

def tool_from_resource(res: Resource) -> Callable[[None],str]:
    async def tool() -> str:
        return await res.read()

    tool.__doc__ = res.description
    tool.__doc__ += """

    Returns:
        str: The requested resource
"""
    tool.__name__ = res.name
    tool.__qualname__ = res.name
    return tool

all_fetch_tools = [tool_from_resource(r) for r in all_http_resources]
