from quri_sdk_mcp.prompts import quri_sdk_start_prompt
from mcp.server.fastmcp.resources import TextResource

_quri_sdk_start = TextResource(
    uri="qsdk://start",
    name="quri_sdk_start",
    title="Overview of QURI SDK tool usage",
    description="""Entry point for any interaction with the QURI SDK MCP server provided tools
    
    This page provides an overview of the tools of the QURI SDK MCP server and their recommended usage based on user prompts. Read this before answering any prompts by the user regarding quri-sdk.""",
    text=quri_sdk_start_prompt,
)

all_text_resources = (_quri_sdk_start,)
