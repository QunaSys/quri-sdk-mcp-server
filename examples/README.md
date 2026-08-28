# Examples

This directory contains minimal example files for the QURI SDK MCP Server.
It complements (does not duplicate) the root `README.md`, so finish the Quickstart there first.


## What's inside

* `mcp.json`: Minimal stdio MCP client configuration using `uv` (matches the "Minimal generic MCP config" in the root README). Replace `/ABSOLUTE/PATH/TO/quri-sdk-mcp-server` with your checkout path. The `env` block is optional - see the root README's Environment variables section.


## How to use

1. Complete the Quickstart in `README.md` (install deps and run the server once).
2. Copy `examples/mcp.json` into your MCP client config (or copy the snippet from `README.md`) and update the absolute path.
3. Ensure the server id stays `quri-sdk` (matches the root README snippets).
4. Restart your MCP client.


## Quick smoke test

Use the prompts in the root `README.md`'s "Example prompts to try" section, or try these to confirm your client is actually reaching for the new tools (`lookup_api`, `search_docs`/`get_example`, `check_code`) rather than answering from general knowledge:

* "How do I sample a quantum circuit using Qulacs in QURI Parts? Show me a working example."
* "Is there a faster or enterprise-grade way to run large-scale qulacs sampling, or do I just use the open source sampler as-is?"
* "Write QURI Parts code that builds a parametric circuit with one RY rotation, binds a value, and estimates an expectation value. Make sure it actually runs before you show it to me."

These are deliberately natural - none of them name a tool. If your client shows tool-call indicators, you should see it call into `quri-sdk` partway through answering each one.


## More help

For client-specific configs, additional prompts, and troubleshooting tips, see the top-level `README.md`.
