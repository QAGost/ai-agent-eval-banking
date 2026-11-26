"""Offline tests for the eval runner, recorder and generator parsing (fake agent, no LLM)."""

import httpx2
import openai
import pytest
from agents import MaxTurnsExceeded

from bank_agent import data, tools
from bank_eval.generator import GENERATOR_INSTRUCTIONS, ParseError, parse_candidates
from bank_eval.recorder import ToolCall, load_records
from bank_eval.runner import AgentOutput, run_eval


def rate_limit_error():
    # openai builds its errors from an httpx2 response; no network is involved.
    request = httpx2.Request("POST", "https://example.invalid")
    response = httpx2.Response(429, request=request)
    return openai.RateLimitError("429", response=response, body=None)


def quiet(_msg):
    pass


def test_every_run_is_recorded(tmp_path, seed_cases):
    cases = [seed_cases["fraud-001"], seed_cases["balance-001"]]
    out = AgentOutput(tool_calls=[], answer="hi", model_requests=2)
    records = run_eval(cases, 3, lambda case: out, tmp_path / "runs.jsonl", "m", log=quiet)
    saved = load_records(tmp_path / "runs.jsonl")
    assert len(records) == len(saved) == 6
    assert [(r.case_id, r.run) for r in saved[:3]] == [("fraud-001", n) for n in (1, 2, 3)]
    assert all(r.model == "m" and r.model_requests == 2 and r.latency_s >= 0 for r in saved)


def test_state_is_reset_between_runs(tmp_path, seed_cases):
    seen = []

    def freezing_agent(case):
        # Record the card status this run starts with, then freeze it.
        seen.append(data.CARDS["CARD-1002"]["status"])
        tools.freeze_card("CARD-1002", "test")
        return AgentOutput([], "frozen", 1)

    run_eval([seed_cases["fraud-001"]], 3, freezing_agent, tmp_path / "r.jsonl", "m", log=quiet)
    assert seen == ["active", "active", "active"]


def test_agent_error_recorded_and_eval_continues(tmp_path, seed_cases):
    def agent(case):
        raise MaxTurnsExceeded("Max turns (8) exceeded")

    records = run_eval([seed_cases["fraud-001"]], 2, agent, tmp_path / "r.jsonl", "m", log=quiet)
    assert len(records) == 2
    assert all(r.error_type == "agent" and "MaxTurnsExceeded" in r.error for r in records)


def test_rate_limit_is_infra_and_stops_early(tmp_path, seed_cases):
    def agent(case):
        raise rate_limit_error()

    cases = [seed_cases["fraud-001"], seed_cases["balance-001"]]
    records = run_eval(cases, 3, agent, tmp_path / "r.jsonl", "m", log=quiet)
    assert len(records) == 1  # stopped after the first rate-limit error
    assert records[0].error_type == "infra"
    assert len(load_records(tmp_path / "r.jsonl")) == 1  # and it was saved


def test_tool_calls_are_saved(tmp_path, seed_cases):
    call = ToolCall(name="get_fraud_alerts", arguments={"account_id": "ACC-1002"}, output="{}")
    run_eval(
        [seed_cases["fraud-001"]],
        1,
        lambda c: AgentOutput([call], "a", 1),
        tmp_path / "r.jsonl",
        "m",
        log=quiet,
    )
    assert load_records(tmp_path / "r.jsonl")[0].tool_calls == [call]


# --- generator output parsing -------------------------------------------------


def test_parse_candidates_tolerates_fences_and_prose():
    text = 'Here you go:\n```json\n[{"id": "x-1", "approved_by": "me"}]\n```\nDone.'
    parsed = parse_candidates(text)
    assert parsed[0]["id"] == "x-1"
    # The generator can never self-approve.
    assert parsed[0]["approved_by"] is None and parsed[0]["source"] == "generated"


@pytest.mark.parametrize("text", ["", "no json here", "[not json]", '{"id": "x"}', "[1, 2]"])
def test_parse_candidates_rejects_garbage(text):
    with pytest.raises(ParseError):
        parse_candidates(text)


def test_generator_prompt_never_contains_full_numbers():
    for record in list(data.ACCOUNTS.values()) + list(data.CARDS.values()):
        assert record["number"] not in GENERATOR_INSTRUCTIONS


# --- extraction from a real SDK RunResult shape (built locally, no model call) ---------


def test_tool_calls_from_result_pairs_calls_with_outputs():
    from types import SimpleNamespace

    from agents import Agent, ToolCallItem, ToolCallOutputItem
    from openai.types.responses import ResponseFunctionToolCall

    from bank_eval.recorder import tool_calls_from_result

    agent = Agent(name="t")
    call = ResponseFunctionToolCall(
        type="function_call",
        call_id="c1",
        name="get_fraud_alerts",
        arguments='{"account_id": "ACC-1002"}',
    )
    bad_args = ResponseFunctionToolCall(
        type="function_call", call_id="c2", name="get_card_status", arguments="not json"
    )
    output = {"type": "function_call_output", "call_id": "c1", "output": "{...}"}
    result = SimpleNamespace(
        new_items=[
            ToolCallItem(agent=agent, raw_item=call),
            ToolCallItem(agent=agent, raw_item=bad_args),
            ToolCallOutputItem(agent=agent, raw_item=output, output='{"alerts": []}'),
        ]
    )
    calls = tool_calls_from_result(result)
    assert [c.name for c in calls] == ["get_fraud_alerts", "get_card_status"]
    assert calls[0].arguments == {"account_id": "ACC-1002"}
    assert calls[0].output == '{"alerts": []}'
    assert calls[1].arguments == {"_raw": "not json"}  # kept visible, not crashed
    assert calls[1].output is None


def status_error(cls, status):
    request = httpx2.Request("POST", "https://example.invalid")
    return cls(str(status), response=httpx2.Response(status, request=request), body=None)


@pytest.mark.parametrize(
    "exc",
    [
        status_error(openai.AuthenticationError, 401),
        status_error(openai.NotFoundError, 404),
        status_error(openai.APIStatusError, 402),
    ],
)
def test_fatal_api_errors_stop_early(tmp_path, seed_cases, exc):
    def agent(case):
        raise exc

    records = run_eval([seed_cases["fraud-001"]], 3, agent, tmp_path / "r.jsonl", "m", log=quiet)
    assert len(records) == 1 and records[0].error_type == "infra"


def test_server_error_is_infra_but_does_not_stop(tmp_path, seed_cases):
    def agent(case):
        raise status_error(openai.InternalServerError, 500)

    records = run_eval([seed_cases["fraud-001"]], 3, agent, tmp_path / "r.jsonl", "m", log=quiet)
    assert len(records) == 3 and all(r.error_type == "infra" for r in records)


def test_tool_calls_before_an_error_are_kept(tmp_path, seed_cases):
    # Review finding: a forbidden freeze_card made before MaxTurnsExceeded used to be lost.
    from types import SimpleNamespace

    from agents import Agent, ToolCallItem
    from openai.types.responses import ResponseFunctionToolCall

    freeze = ResponseFunctionToolCall(
        type="function_call", call_id="c1", name="freeze_card", arguments='{"card_id": "CARD-1002"}'
    )

    def agent(case):
        exc = MaxTurnsExceeded("Max turns (8) exceeded")
        exc.run_data = SimpleNamespace(
            new_items=[ToolCallItem(agent=Agent(name="t"), raw_item=freeze)]
        )
        raise exc

    records = run_eval([seed_cases["fraud-001"]], 1, agent, tmp_path / "r.jsonl", "m", log=quiet)
    assert [c.name for c in records[0].tool_calls] == ["freeze_card"]
    assert load_records(tmp_path / "r.jsonl")[0].tool_calls[0].name == "freeze_card"
