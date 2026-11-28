"""Run the banking agent once from the command line.

Usage:
    python run_agent.py 'Is the $1,240 charge on my account suspicious?'
    python run_agent.py --mcp 'Is the $1,240 charge on my account suspicious?'

Use single quotes: in bash and PowerShell, "$1" inside double quotes is expanded.

--mcp: the agent gets its tools from the mock bank MCP server (bank_mcp/server.py, started as
a subprocess) instead of calling the Python functions directly. Same tools, same data.

Prints the final answer, every tool call (name + arguments) the agent made,
the run latency, the number of model requests used and which model served them.
"""

import asyncio
import sys
import time

from agents import Runner, ToolCallItem

from bank_agent.agent import ServedModelLog, bank_mcp_server, build_agent

MAX_TURNS = 8


async def run(question: str, use_mcp: bool, served: ServedModelLog):
    if not use_mcp:
        return await Runner.run(build_agent(served_models=served), question, max_turns=MAX_TURNS)
    # The server process lives for the duration of this block, then is shut down.
    async with bank_mcp_server() as server:
        agent = build_agent(served_models=served, mcp_servers=[server])
        return await Runner.run(agent, question, max_turns=MAX_TURNS)


def main() -> int:
    args = sys.argv[1:]
    use_mcp = bool(args) and args[0] == "--mcp"  # only as the first argument
    words = args[1:] if use_mcp else args
    if not words:
        print('Usage: python run_agent.py [--mcp] "<your question>"')
        return 1
    question = " ".join(words)

    served = ServedModelLog()
    start = time.perf_counter()
    result = asyncio.run(run(question, use_mcp, served))
    latency_s = time.perf_counter() - start
    # Each model call is one raw response; this is what counts against API limits.
    model_requests = len(result.raw_responses)

    # Collect tool calls from the run's items; these are what later labs will evaluate.
    tool_calls = [
        (item.raw_item.name, item.raw_item.arguments)
        for item in result.new_items
        if isinstance(item, ToolCallItem)
    ]

    print("=== Final answer ===")
    print(result.final_output)
    print(f"\n=== Tool calls ({'MCP server' if use_mcp else 'direct'}) ===")
    if not tool_calls:
        print("(none)")
    for i, (name, args) in enumerate(tool_calls, start=1):
        print(f"{i}. {name}({args})")
    print("\n=== Run stats ===")
    print(f"Latency: {latency_s:.2f}s")
    print(f"Model requests: {model_requests}")
    print(f"Served by: {', '.join(served.take()) or 'not recorded'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
