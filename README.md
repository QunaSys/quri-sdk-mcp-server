# QURI Parts MCP server

The purpose of this project is to provide an MCP server for LLMs assisting with
QURI SDK code generation. It exposes tools for looking up real, version-correct
API signatures, searching QURI SDK documentation, fetching source/example code,
and validating generated code.

This repo uses UV for package management.

## Tools

| Tool | Purpose |
| --- | --- |
| `lookup_api` | Looks up the actual signature, docstring, and source location for a `quri_parts`/`quri_algo`/`quri_vm` symbol, introspected from the interpreter your project actually uses. Also flags known Enterprise `.plus` upgrades. |
| `search_docs` | Lexical (keyword) search over QURI SDK documentation - tutorials, how-to guides, reference pages, and release notes. |
| `get_example` | `search_docs` pre-restricted to tutorial and how-to content, for "show me an example" style requests. |
| `check_code` | Creates a temporary virtual environment, type-checks generated code with Pyright, and optionally executes it. |
| `fetch_as_markdown` | Fetches a URL and converts its HTML content to Markdown. |
| `fetch_raw_python` | Fetches a raw file (e.g. Python source) from the quri-sdk repository. |
| `fetch_raw_python_notebook` | Fetches a raw Jupyter notebook from the quri-sdk repository. |

A handful of additional tools (e.g. `quri_sdk_start`, `tutorial_start`,
`quri_sdk_source_code_tree`) wrap individual hardcoded documentation/source
resources - see `quri_sdk_mcp/markdown_resources.py`,
`quri_sdk_mcp/text_resources.py`, and
`quri_sdk_mcp/python_source_code_resources.py`.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `QURI_SDK_MCP_PYTHON` | Path to the Python interpreter of the project you're assisting with. `lookup_api`, `search_docs`, and `get_example` introspect and resolve versions against this interpreter so results match what's actually installed. Falls back to this server's own interpreter (which bundles the OSS `quri-sdk` install) if unset. |
| `GITHUB_TOKEN` | A GitHub token used to authenticate `api.github.com` requests (source-tree listings, etc.), raising the otherwise low unauthenticated rate limit. Optional - tools that use it still work unauthenticated, just with a lower rate limit. |

Note: `quri-sdk` on PyPI is an empty meta-package (it exists only to pull in
the real, separately-versioned `quri_parts`/`quri_algo`/`quri_vm` packages as
dependencies) - `importlib.metadata.version("quri-sdk")` will resolve, but the
package itself has no code. This is why version resolution
(`quri_sdk_mcp/env_resolution.py`) checks `quri-parts`'s version rather than
`quri-sdk`'s.

## Installation

```
pip install .
```

This installs a `quri-sdk-mcp` command on `PATH`.

## Config

If installed via `pip install .`, the configuration file for this MCP server
should look something like

```
{
    "mcpServers": {
        "quri_sdk": {
            "command": "quri-sdk-mcp",
            "env": {
                "QURI_SDK_MCP_PYTHON": "/path/to/your/project/.venv/bin/python",
                "GITHUB_TOKEN": "ghp_..."
            }
        }
    }
}
```

For development from source instead, run it via `uv`:

```
{
    "mcpServers": {
        "quri_sdk": {
            "command": "uv",
            "args": [
                "--directory",
                "PATH/TO/THIS/MODULE",
                "run",
                "quri_sdk_mcp/server.py"
            ],
            "env": {
                "QURI_SDK_MCP_PYTHON": "/path/to/your/project/.venv/bin/python",
                "GITHUB_TOKEN": "ghp_..."
            }
        }
    }
}
```

or if you use WSL

```
{
    "mcpServers": {
        "quri_sdk": {
            "command": "wsl",
            "args": [
                "bash",
                "-c",
                "PATH/TO/UV/EXECUTABLE/IN/WSL/uv --directory PATH/TO/THIS/MODULE run quri_sdk_mcp/server.py"
            ],
            "env": {
                "QURI_SDK_MCP_PYTHON": "/path/to/your/project/.venv/bin/python",
                "GITHUB_TOKEN": "ghp_..."
            }
        }
    }
}
```

Both `env` entries are optional - omit them to use this server's own bundled
interpreter and an unauthenticated (lower rate limit) GitHub client.
