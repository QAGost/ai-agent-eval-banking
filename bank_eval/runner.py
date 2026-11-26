"""Runs each case N times and records every run.

The agent call is injected as an `execute` function, so the runner itself can be tested
offline with a fake agent. Only `make_live_executor` touches the real model.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bank_agent import data
from bank_eval.cases import EvalCase
from bank_eval.recorder import RunRecord, ToolCall, append_record, tool_calls_from_result

if TYPE_CHECKING:  # type hints only: importing the agent pulls in the SDK and openai
    from bank_agent.agent import ServedModelLog

# Rough average used only for the up-front budget estimate (one run = several model calls).
REQUESTS_PER_RUN_ESTIMATE = 4


@dataclass
class AgentOutput:
    tool_calls: list[ToolCall]
    answer: str
    model_requests: int


Executor = Callable[[EvalCase], AgentOutput]


def estimate_requests(n_cases: int, runs: int) -> int:
    return n_cases * runs * REQUESTS_PER_RUN_ESTIMATE


def classify_error(exc: Exception) -> str:
    """'infra' for API/network/rate-limit problems (not scored), 'agent' for everything else."""
    import openai

    return "infra" if isinstance(exc, openai.APIError) else "agent"


def is_fatal(exc: Exception) -> bool:
    """Errors that will hit every later run too: stop instead of wasting requests."""
    import openai

    fatal = (
        openai.RateLimitError,  # e.g. free tier daily cap
        openai.AuthenticationError,  # bad API key
        openai.PermissionDeniedError,
        openai.NotFoundError,  # unknown model id
    )
    return isinstance(exc, fatal) or getattr(exc, "status_code", None) == 402  # no credits


def partial_tool_calls(exc: Exception) -> list[ToolCall]:
    """Tool calls made before the error, when the SDK attached them (e.g. MaxTurnsExceeded).

    Keeps evidence such as a forbidden freeze_card that happened before the run failed.
    """
    run_data = getattr(exc, "run_data", None)
    return tool_calls_from_result(run_data) if run_data is not None else []


def run_eval(
    cases: list[EvalCase],
    runs: int,
    execute: Executor,
    records_path: str | Path,
    model: str,
    log: Callable[[str], None] = print,
    served_log: "ServedModelLog | None" = None,
) -> list[RunRecord]:
    """Run every case `runs` times; append each run to records_path as it finishes.

    Stops early on errors that would repeat on every run (rate limit / daily cap, bad key,
    unknown model, no credits). Records written so far are kept and can be scored as an incomplete run.
    """
    records: list[RunRecord] = []
    for case in cases:
        for run in range(1, runs + 1):
            data.reset_data()  # each run starts from the same state (freeze_card mutates it)
            record = RunRecord(
                case_id=case.id,
                run=run,
                model=model,
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            if served_log is not None:
                served_log.take()  # drop anything left over from outside this run
            start = time.perf_counter()
            stop = False
            try:
                out = execute(case)
                record.tool_calls = out.tool_calls
                record.answer = out.answer
                record.model_requests = out.model_requests
            # Catch everything on purpose: one bad run is recorded and must not end the eval.
            except Exception as exc:  # noqa: BLE001
                record.error = f"{type(exc).__name__}: {exc}"[:500]
                record.error_type = classify_error(exc)
                record.tool_calls = partial_tool_calls(exc)
                stop = is_fatal(exc)
            record.latency_s = round(time.perf_counter() - start, 3)
            if served_log is not None:
                record.served_models = served_log.take()
            append_record(records_path, record)
            records.append(record)
            status = "ERROR " + record.error_type if record.error else "done"
            log(f"  {case.id} run {run}/{runs}: {status} ({record.latency_s:.1f}s)")
            if stop:
                log(
                    "Stopping early (this error would repeat on every run). Partial results are saved."
                )
                return records
    return records


def make_live_executor(agent, max_turns: int = 8) -> Executor:
    """Executor that calls the real agent (uses API requests)."""
    from agents import Runner

    def execute(case: EvalCase) -> AgentOutput:
        result = Runner.run_sync(agent, case.prompt, max_turns=max_turns)
        return AgentOutput(
            tool_calls=tool_calls_from_result(result),
            answer=str(result.final_output),
            model_requests=len(result.raw_responses),
        )

    return execute
