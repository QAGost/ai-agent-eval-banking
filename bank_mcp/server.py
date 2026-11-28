"""Mock MCP server: the six Northwind Demo Bank tools over stdio.

Run it:      python -m bank_mcp.server            (an MCP client starts it as a subprocess)
Inspect it:  mcp dev bank_mcp/server.py           (opens the MCP Inspector in a browser)

The tools are the same plain functions the direct-mode agent uses (bank_agent.tools), backed by
the same synthetic data (bank_agent.data), so both modes behave identically. The data is reset
at startup; freeze_card changes it only in this server process's memory.

Test-only fault mode (bank_mcp/faults.py), for robustness tests. Set BANK_MCP_FAULT to "<mode>:<tool name>":
  slow:<tool>    the tool waits BANK_MCP_SLOW_SECONDS (default 10) before answering
  error:<tool>   the tool fails (the client receives an MCP error result)
  inject:<tool>  the tool's normal JSON result gets an extra field with prompt-injection text
Unset (the default), the server has no faults. Never set it outside tests.

Note: mcp 2.x renamed FastMCP to MCPServer (mcp.server.mcpserver); this file uses 2.x.
"""

import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

if not __package__:
    # Loaded as a plain file (`mcp dev bank_mcp/server.py`), which puts only bank_mcp/ on the
    # import path: add the repo root so `bank_agent` and `bank_mcp` can be imported.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bank_agent import data  # after the path fix above
from bank_agent.tools import TOOL_FUNCTIONS
from bank_mcp.faults import parse_fault, parse_slow_seconds, with_fault


def build_server(fault: tuple[str, str] | None = None, slow_seconds: float = 10.0) -> MCPServer:
    """Create the MCP server with the six bank tools (one of them faulty, if fault is given)."""
    server = MCPServer(
        name="northwind-demo-bank",
        instructions="Mock tools of a fictional demo bank. All data is synthetic.",
    )
    for fn in TOOL_FUNCTIONS:
        tool = fn
        if fault is not None and fault[1] == fn.__name__:
            tool = with_fault(fn, fault[0], slow_seconds)
        # structured_output=False: return the tool's JSON string as plain text content,
        # exactly what the direct-mode function_tool gives the model.
        server.tool(structured_output=False)(tool)
    return server


def server_from_env() -> MCPServer:
    """Build the server from env vars; reset the fake data so every start is identical."""
    data.reset_data()
    fault = parse_fault(os.getenv("BANK_MCP_FAULT"))
    if fault is not None:
        # stderr, never stdout: stdout carries the MCP protocol messages.
        print(f"bank_mcp: TEST FAULT MODE {fault[0]}:{fault[1]}", file=sys.stderr)
    return build_server(fault, parse_slow_seconds(os.getenv("BANK_MCP_SLOW_SECONDS")))


# Module-level name `server` is what `mcp dev bank_mcp/server.py` looks for.
server = server_from_env()

if __name__ == "__main__":
    server.run("stdio")
