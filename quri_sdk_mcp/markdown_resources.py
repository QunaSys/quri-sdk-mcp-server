from pydantic import Field
from mcp.server.fastmcp.resources import Resource
from quri_sdk_mcp.fetch.fetcher import FetchRequestArgs, FetchResponse, Fetcher


class MarkdownResource(Resource):
    """Fetch HTML content and convert it to markdown."""

    url: str = Field(description="URL to fetch content from")

    async def get_fetch_response(self) -> FetchResponse:
        """Fetch a website, convert its HTML content to Markdown, and return it.

        Returns:
            FetchResponse: An object containing the Markdown content or an error message.
                        On success, isError is false and content contains the Markdown text.
                        On failure, isError is true and errorMessage contains the error details.
        """
        args = FetchRequestArgs(url=self.url, headers=None)
        return await Fetcher.markdown(args)

    async def read(self) -> str:
        """Fetch the markdown from an HTML resource.

        Returns:
            str: The markdown contents of the FetchResponse object
        """
        response = await self.get_fetch_response()
        markdown = ""
        for c in response.content:
            markdown += c["text"]
        return markdown


_tutorial_start = MarkdownResource(
    uri="qsdk://docs/tutorials/general",
    url="https://quri-sdk.qunasys.com/docs/tutorials/general/",
    name="tutorial_start",
    title="Overview of QURI SDK usage",
    description="""QURI SDK development workflow

    This page gives an overview of the development workflow of QURI SDK. To understand the recommended usage of QURI SDK please start here.
""",
)

_examples_quri_algo_vm = MarkdownResource(
    uri="qsdk://docs/tutorials/quri-algo",
    url="https://quri-sdk.qunasys.com/docs/examples/quri-algo-vm/",
    name="examples_quri_algo_vm",
    title="Examples of QURI Algo and QURI VM usage",
    description="""This is the index page of the example codes for QURI Algo and QURI VM. Navigate from here to find all of the example codes.
""",
)

_examples_quri_parts = MarkdownResource(
    uri="qsdk://docs/tutorials/quri-parts",
    url="https://quri-sdk.qunasys.com/docs/examples/quri-parts/",
    name="examples_quri_parts",
    title="Examples of QURI Parts usage",
    description="""This is the index page of the example codes for QURI Parts. Navigate from here to find all of the example codes.
""",
)

_tutorial_quri_parts_qsub = MarkdownResource(
    uri="qsdk://docs/tutorials/quri-parts/advanced/qsub",
    url="https://quri-sdk.qunasys.com/docs/tutorials/quri-parts/advanced/qsub/",
    name="tutorial_quri_parts_qsub",
    title="Tutorial for quri-parts-qsub",
    description="""This is a tutorial for quri-parts-qsub, which is a module for circuit synthesis.
""",
)

all_markdown_resources = (
    _tutorial_start,
    _examples_quri_algo_vm,
    _examples_quri_parts,
    _tutorial_quri_parts_qsub,
)
