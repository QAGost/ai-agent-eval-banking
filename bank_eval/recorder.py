"""Run records: everything we need to score (and re-score) one agent run later.

CLAUDE.md requires recording every run: case id, run number, tool calls, answer,
latency and errors. Records are written as JSONL so results can be compared over time.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]
    output: str | None = None  # the tool's JSON string result, if one was returned


class RunRecord(BaseModel):
    case_id: str
    run: int  # 1-based run number within the case
    model: str
    started_at: str
    tool_calls: list[ToolCall] = []
    answer: str | None = None
    latency_s: float = 0.0
    model_requests: int = 0
    error: str | None = None
    # "infra" = API/network/rate-limit problem: the run is NOT scored (not the agent's fault).
    # "agent" = the agent itself failed (e.g. hit max_turns): counts as a failed run.
    error_type: Literal["infra", "agent"] | None = None


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {"_raw": raw}
    except json.JSONDecodeError:
        return {"_raw": raw}  # keep malformed arguments visible instead of crashing


def _call_id(raw_item: Any) -> str | None:
    if isinstance(raw_item, dict):
        return raw_item.get("call_id")
    return getattr(raw_item, "call_id", None)


def tool_calls_from_result(result: Any) -> list[ToolCall]:
    """Extract tool calls and their outputs from an Agents SDK RunResult."""
    from agents import ToolCallItem, ToolCallOutputItem  # imported here: SDK only needed live

    calls: list[ToolCall] = []
    by_id: dict[str, ToolCall] = {}
    for item in result.new_items:
        if isinstance(item, ToolCallItem):
            raw = item.raw_item
            call = ToolCall(name=raw.name, arguments=_parse_args(raw.arguments))
            calls.append(call)
            if (cid := _call_id(raw)) is not None:
                by_id[cid] = call
        elif isinstance(item, ToolCallOutputItem):
            call = by_id.get(_call_id(item.raw_item))
            if call is not None:
                call.output = str(item.output)
    return calls


def append_record(path: str | Path, record: RunRecord) -> None:
    """Append one run immediately, so a crash or rate limit never loses earlier runs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(record.model_dump_json() + "\n")


def load_records(path: str | Path) -> list[RunRecord]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [RunRecord.model_validate_json(line) for line in lines if line.strip()]
