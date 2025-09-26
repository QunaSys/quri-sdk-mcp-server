# QURI Parts MCP server

The purpose of this project is to provide an MCP server for LLMs.

This repo uses UV for package management 

## Config

The configuration file for this MCP server should look something like

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
            ]
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
            ]
        }
    }
}
```
