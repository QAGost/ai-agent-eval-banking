"""Offline tests for recording which model served each request.

The end-to-end test runs the REAL agent, recorder and runner against a fake OpenRouter
(an httpx2 MockTransport): no network, no LLM, and only a dummy API key.
"""

import asyncio
import json

import httpx2
import pytest

from bank_agent.agent import ServedModelLog, build_agent
from bank_eval.recorder import RunRecord, load_records
from bank_eval.runner import AgentOutput, make_live_executor, run_eval

COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


def completion(model, message, finish_reason):
    """A minimal OpenAI-compatible chat completion body, as OpenRouter returns it."""
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def verify_call_then_answer():
    """Fake OpenRouter: 1st request -> tool call (model A), 2nd -> final answer (model B)."""
    tool_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "verify_customer",
                    "arguments": json.dumps(
                        {"customer_id": "CUST-1002", "last4_ssn_or_pin": "7390"}
                    ),
                },
            }
        ],
    }
    responses = iter(
        [
            completion("vendor/model-a:free", tool_call, "tool_calls"),
            completion(
                "vendor/model-b:free", {"role": "assistant", "content": "Verified."}, "stop"
            ),
        ]
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx2.Response(200, json=next(responses))

    return httpx2.MockTransport(handler)


def response(status, path, body, content_type="application/json"):
    request = httpx2.Request("POST", f"https://openrouter.ai{path}")
    headers = {"content-type": content_type}
    return httpx2.Response(status, request=request, content=body, headers=headers)


# --- the response hook -----------------------------------------------------------


def test_hook_records_model_from_completion():
    log = ServedModelLog()
    body = json.dumps({"model": "vendor/x:free"}).encode()
    asyncio.run(log.on_response(response(200, "/api/v1/chat/completions", body)))
    assert log.take() == ["vendor/x:free"]
    assert log.take() == []  # take() clears


@pytest.mark.parametrize(
    ("status", "path", "body"),
    [
        (429, "/api/v1/chat/completions", b'{"model": "x"}'),  # errors are not "served"
        (200, "/api/v1/models", b'{"model": "x"}'),  # other endpoints ignored
        (200, "/api/v1/chat/completions", b"not json"),
        (200, "/api/v1/chat/completions", b"[1, 2]"),
        (200, "/api/v1/chat/completions", b'{"model": ""}'),
    ],
)
def test_hook_ignores_everything_else(status, path, body):
    log = ServedModelLog()
    asyncio.run(log.on_response(response(status, path, body)))
    assert log.take() == []


def test_hook_skips_streamed_responses():
    log = ServedModelLog()
    sse = b'data: {"model": "x"}\n\n'
    asyncio.run(
        log.on_response(response(200, "/api/v1/chat/completions", sse, "text/event-stream"))
    )
    assert log.take() == []


# --- runner -----------------------------------------------------------------------


def test_runner_assigns_served_models_per_run(tmp_path, seed_cases):
    log = ServedModelLog()
    log.add("leftover/from-before")  # must not leak into run 1

    calls = []

    def agent(case):
        calls.append(case.id)
        log.add("vendor/model-a:free")  # what the HTTP hook would do on each response
        if len(calls) == 2:
            raise RuntimeError("boom")  # second run fails after one request
        return AgentOutput([], "ok", 1)

    records = run_eval(
        [seed_cases["fraud-001"]], 2, agent, tmp_path / "r.jsonl", "m", lambda _: None, log
    )
    assert [r.served_models for r in records] == [["vendor/model-a:free"]] * 2
    assert records[1].error  # served models are kept even when the run fails


def test_old_records_without_served_models_still_load(tmp_path):
    old = {"case_id": "c", "run": 1, "model": "m", "started_at": "t"}
    (tmp_path / "runs.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert load_records(tmp_path / "runs.jsonl")[0].served_models == []


# --- end to end against a fake OpenRouter --------------------------------------------


def test_live_pipeline_offline_end_to_end(tmp_path, seed_cases, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-key-for-offline-test")
    monkeypatch.setenv("AGENT_MODEL", "openrouter/free")
    log = ServedModelLog()
    agent = build_agent(max_retries=0, served_models=log, transport=verify_call_then_answer())

    records = run_eval(
        [seed_cases["verify-wrong-pin-001"]],
        1,
        make_live_executor(agent),
        tmp_path / "runs.jsonl",
        "openrouter/free",
        lambda _: None,
        log,
    )
    record: RunRecord = load_records(tmp_path / "runs.jsonl")[0]
    assert records[0] == record
    assert record.error is None
    assert record.served_models == ["vendor/model-a:free", "vendor/model-b:free"]
    assert record.model_requests == 2
    assert [c.name for c in record.tool_calls] == ["verify_customer"]
    assert json.loads(record.tool_calls[0].output)["verified"] is True  # real tool ran
    assert record.answer == "Verified."
