# QURI SDK MCP Server

This repository provides an MCP (Model Context Protocol) server that helps LLM-based coding tools generate QURI SDK code correctly: it looks up real, version-correct API signatures, searches QURI SDK documentation, fetches example code, and validates generated code before it's shown to you.
It's designed to be used with MCP-compatible clients such as Claude Desktop, Claude Code, and Cursor.

This repo uses UV for package management.


## Quickstart (copy & paste)

### Prerequisites

* **Python 3.10+**
* **uv** (recommended Python package manager)

  * Install: [https://docs.astral.sh/uv/](https://docs.astral.sh/uv/)


### 1. Clone the repository

```bash
git clone https://github.com/QunaSys/quri-sdk-mcp-server.git
cd quri-sdk-mcp-server
```


### 2. Install dependencies

```bash
uv sync
```

This creates a virtual environment and installs all required dependencies.
If you'd rather install this as a regular package instead of running from a clone, see [Installation](#installation) below.


### 3. Run the MCP server

```bash
uv run python -m quri_sdk_mcp.server
```

If the server starts **without errors or tracebacks**, it is running correctly.

> The server communicates over **stdio**, so it will appear idle after startup. This is expected.


### 4. Verify it works (recommended)

You can verify that the server starts correctly by simply running the command above and confirming:

* No Python exceptions are printed
* The process stays alive

For a deeper check that lets you actually call each tool by hand, run the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) against it:

```bash
uv run mcp dev quri_sdk_mcp/server.py
```

This opens a local web UI where you can list every registered tool and call it directly with a form, without needing a full editor.

The server is now ready to be used by an MCP-compatible client.


## Installation

To install this as a regular package instead of running it from a clone:

```bash
pip install .
```

This installs a `quri-sdk-mcp` command on `PATH`, which you can point an MCP client at directly (see [Using with MCP Clients](#using-with-mcp-clients) below).


## Tools

| Tool | Purpose |
| --- | --- |
| `lookup_api` | Looks up the actual signature, docstring, source location, and source code for a `quri_parts`/`quri_algo`/`quri_vm` symbol, introspected from the interpreter your project actually uses. Also flags known Enterprise `.plus` upgrades. |
| `search_docs` | Lexical (keyword) search over QURI SDK documentation - tutorials, how-to guides, reference pages, and release notes. |
| `get_example` | `search_docs` pre-restricted to tutorial and how-to content, for "show me an example" style requests. |
| `fetch_example_source` | Fetches the exact runnable source (notebook or markdown) behind a `search_docs`/`get_example` result. |
| `check_code` | Creates a temporary virtual environment, type-checks generated code with Pyright, and optionally executes it. |

A handful of additional tools (e.g. `quri_sdk_start`, `tutorial_start`, `quri_sdk_source_code_tree`) wrap individual hardcoded documentation/source resources - see `quri_sdk_mcp/markdown_resources.py`, `quri_sdk_mcp/text_resources.py`, and `quri_sdk_mcp/python_source_code_resources.py`.


## Environment variables

| Variable | Purpose |
| --- | --- |
| `QURI_SDK_MCP_PYTHON` | Path to the Python interpreter of the project you're assisting with. `lookup_api`, `search_docs`, and `get_example` introspect and resolve versions against this interpreter so results match what's actually installed. Falls back to this server's own interpreter (which bundles the OSS `quri-sdk` install) if unset. |
| `GITHUB_TOKEN` | A GitHub token used to authenticate `api.github.com` requests (source-tree listings, etc.), raising the otherwise low unauthenticated rate limit. Optional - tools that use it still work unauthenticated, just with a lower rate limit. |

Both variables are optional - omit them to use this server's own bundled interpreter and an unauthenticated (lower rate limit) GitHub client.

Note: `quri-sdk` on PyPI is an empty meta-package (it exists only to pull in the real, separately-versioned `quri_parts`/`quri_algo`/`quri_vm` packages as dependencies) - `importlib.metadata.version("quri-sdk")` will resolve, but the package itself has no code.
This is why version resolution (`quri_sdk_mcp/env_resolution.py`) checks `quri-parts`'s version rather than `quri-sdk`'s.


## Using with MCP Clients

### Claude Desktop (macOS / Windows)

Add the following entry to your Claude Desktop MCP configuration file.
If you installed via `pip install .`:

```json
{
  "mcpServers": {
    "quri-sdk": {
      "command": "quri-sdk-mcp",
      "env": {
        "QURI_SDK_MCP_PYTHON": "/path/to/your/project/.venv/bin/python",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

If you're running from a clone instead, via `uv`:

```json
{
  "mcpServers": {
    "quri-sdk": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/quri-sdk-mcp-server",
        "run",
        "python",
        "-m",
        "quri_sdk_mcp.server"
      ],
      "env": {
        "QURI_SDK_MCP_PYTHON": "/path/to/your/project/.venv/bin/python",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

Replace `/ABSOLUTE/PATH/TO/quri-sdk-mcp-server` with the actual path to the repository.

Restart Claude Desktop after updating the config.


### WSL (Windows Subsystem for Linux)

```json
{
  "mcpServers": {
    "quri-sdk": {
      "command": "wsl",
      "args": [
        "bash",
        "-lc",
        "cd /path/to/quri-sdk-mcp-server && uv run python -m quri_sdk_mcp.server"
      ],
      "env": {
        "QURI_SDK_MCP_PYTHON": "/path/to/your/project/.venv/bin/python",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```


### Minimal generic MCP config (stdio)

```json
{
  "command": "uv",
  "args": [
    "--directory",
    "/path/to/quri-sdk-mcp-server",
    "run",
    "python",
    "-m",
    "quri_sdk_mcp.server"
  ]
}
```

A ready-to-use copy of this configuration lives at `examples/mcp.json` if you prefer to start from a file instead of copying the snippet.


## Example prompts to try

Once connected, try prompts like these in your MCP client - none of them name a tool, but they should trigger `lookup_api`, `search_docs`/`get_example`, and `check_code` on their own:

* "How do I sample a quantum circuit using Qulacs in QURI Parts? Show me a working example."
* "Is there a faster or enterprise-grade way to run large-scale qulacs sampling, or do I just use the open source sampler as-is?"
* "Write QURI Parts code that builds a parametric circuit with one RY rotation, binds a value, and estimates an expectation value. Make sure it actually runs before you show it to me."


## Troubleshooting

### `uv: command not found`

* Make sure `uv` is installed and on your `PATH`
* Restart your terminal after installation

### Python version errors

* Ensure `python --version` reports **3.10 or newer**
* If multiple Python versions are installed, verify that `uv` is using the correct one

### Server starts but no tools appear

Checklist:

* Did you restart your MCP client after editing the config?
* Is the repository path absolute (not `~`)?
* Are there any errors printed when starting the server manually?

### Tool calls seem to hang or get skipped

Some MCP clients require you to approve a tool call the first time it's used in a session (a permission prompt).
If a client is running non-interactively (e.g. headless/scripted), it can't answer that prompt, and the call will be skipped rather than executed.

### Network or SSL errors

Some tools fetch content from:

* [https://docs.qunasys.com](https://docs.qunasys.com)
* [https://github.com/QunaSys](https://github.com/QunaSys)

If you are behind a corporate proxy or custom SSL setup, ensure outbound HTTPS access is allowed.


## Development notes

* The server is intentionally **stateless** and communicates via stdio
* Core functionality lives in `quri_sdk_mcp/`
* Adding a new hardcoded documentation/source resource (the `markdown_resources.py`/`text_resources.py`/`python_source_code_resources.py` pattern) needs no runtime changes; extending `search_docs`'s corpus or `lookup_api`'s introspection does involve code changes in `quri_sdk_mcp/corpus/` and `quri_sdk_mcp/introspection.py` respectively
