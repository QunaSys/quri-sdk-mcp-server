from mcp.server.fastmcp.resources import HttpResource

_tutorial_start = HttpResource(
    uri="qsdk://docs/tutorials/general",
    mime_type="text/html",
    url="https://quri-sdk.qunasys.com/docs/tutorials/general/",
    name="tutorial_start",
    title="Overview of QURI SDK usage",
    description="""QURI SDK development workflow

            This page gives an overview of the development workflow of QURI SDK. To understand the recommended usage of QURI SDK please start here.
""",
)

# _tutorial_toc = HttpResource(
#     uri="qsdk://docs/tutorials/general",
#     mime_type="text/html",
#     url="https://quri-sdk.qunasys.com/docs/tutorials/general/",
#     name="QURI SDK tutorial root",
#     title="Overview of QURI SDK usage",
#     description="""QURI SDK development workflow

#             This page gives an overview of the development workflow of QURI SDK. To understand the recommended usage of QURI SDK please start here.
# """,
# )

all_http_resources = (
    _tutorial_start,
    # _tutorial_toc,
    )
