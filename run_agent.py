"""Run the banking agent once from the command line.

Usage:
    python run_agent.py "Is the $1,240 charge on my account suspicious?"

Prints the final answer and every tool call (name + arguments) the agent made.
"""

import sys

from agents import Runner, ToolCallItem

from bank_agent.agent import build_agent

MAX_TURNS = 8


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python run_agent.py "<your question>"')
        return 1
    question = " ".join(sys.argv[1:])

    agent = build_agent()
    result = Runner.run_sync(agent, question, max_turns=MAX_TURNS)

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
