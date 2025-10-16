from typing import Callable

from mcp.server.fastmcp.resources import Resource
from quri_sdk_mcp.markdown_resources import MarkdownResource
from quri_sdk_mcp.fetch.fetcher import FetchResponse


def tool_from_resource(res: Resource) -> Callable[[None], FetchResponse]:
    if isinstance(res, MarkdownResource):

        async def tool() -> FetchResponse:
            return await res.get_fetch_response()

    else:

        async def tool() -> FetchResponse:
            text = await res.read()
            response = FetchResponse(
                content=[{"type": "text", "text": text}], isError=False
            )
            return response

    tool.__doc__ = res.description
    tool.__doc__ += """

    Returns:
        FetchResponse: The requested resource
"""
    tool.__name__ = res.name
    tool.__qualname__ = res.name
    return tool
