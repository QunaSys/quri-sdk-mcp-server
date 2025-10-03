from mcp.server.fastmcp.resources.types import HttpResource

_quri_algo_algorithm_base = HttpResource(
    uri="qsdk://source/algo/algorithms/base",
    url="https://raw.githubusercontent.com/QunaSys/quri-sdk/refs/heads/main/quri-algo/quri_algo/algo/interface.py",
    mime_type="text/x-python",
    name="quri_algo_algorithm_base",
    title="Base classes and definitions for algorithms",
    description="""This python source file details the interface for quri-algo style Algorithms. Algorithms written for quri-algo should follow this style.
""",
)

_quri_sdk_source_file_tree = HttpResource(
    uri="qsdk://source/tree",
    url="https://api.github.com/repos/QunaSys/quri-sdk/git/trees/main?recursive=1",
    mime_type="application/json",
    name="quri_sdk_source_code_tree",
    title="Source code tree for quri-sdk codebase",
    description="""This resource provides the source code tree for quri-sdk.
    
    Using the information here you can get an overview of the code-base structure and source files to fetch and analyse.""",
)

all_python_source_code_resources = (
    _quri_algo_algorithm_base,
    _quri_sdk_source_file_tree,
)
