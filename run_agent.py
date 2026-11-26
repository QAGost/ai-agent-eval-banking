"""Run the banking agent once from the command line.

Usage:
    python run_agent.py 'Is the $1,240 charge on my account suspicious?'

Use single quotes: in bash and PowerShell, "$1" inside double quotes is expanded.

Prints the final answer, every tool call (name + arguments) the agent made,
the run latency, the number of model requests used and which model served them.
"""

import sys
import time

from agents import Runner, ToolCallItem

from bank_agent.agent import ServedModelLog, build_agent

MAX_TURNS = 8


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python run_agent.py "<your question>"')
        return 1
    question = " ".join(sys.argv[1:])

    served = ServedModelLog()
    agent = build_agent(served_models=served)
    start = time.perf_counter()
    result = Runner.run_sync(agent, question, max_turns=MAX_TURNS)
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
    print("\n=== Tool calls ===")
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
