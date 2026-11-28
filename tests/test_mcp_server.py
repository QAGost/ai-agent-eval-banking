"""Offline tests for the mock bank MCP server (bank_mcp/server.py).

Every test starts the real server as a subprocess and talks to it over stdio with the
official MCP client (ClientSession + stdio_client), or through the real agent in MCP mode.
No LLM and no network: the agent tests use a scripted fake OpenRouter (httpx2 MockTransport).

What the agent-level robustness tests prove: our pipeline handles a slow, failing or
prompt-injecting tool safely (the run finishes, the problem reaches the model only as tool
data, and no card is frozen). Whether a REAL model resists the injection is a live-eval question.
"""

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager

import httpx2
import pytest
from agents import Runner, ToolCallItem
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError

from bank_agent import data, tools
from bank_agent.agent import REPO_ROOT, bank_mcp_server, build_agent
from bank_mcp.faults import INJECTION_TEXT, parse_fault, parse_slow_seconds

TOOL_NAMES = [fn.__name__ for fn in tools.TOOL_FUNCTIONS]


@asynccontextmanager
async def mcp_session(env: dict[str, str] | None = None):
    """Start bank_mcp.server as a subprocess and open an initialized MCP client session."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "bank_mcp.server"], env=env or {}, cwd=REPO_ROOT
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session, name, **arguments):
    """Call a tool; return (is_error, text of the first content block)."""
    result = await session.call_tool(name, arguments)
    return result.is_error, result.content[0].text


# --- (a) tool list and schemas ----------------------------------------------------


def test_lists_all_six_tools_with_the_same_schemas_as_direct_mode():
    async def scenario():
        async with mcp_session() as session:
            return (await session.list_tools()).tools

    listed = {t.name: t for t in asyncio.run(scenario())}
    assert sorted(listed) == sorted(TOOL_NAMES)
    direct = {t.name: t.params_json_schema for t in tools.ALL_TOOLS}
    for name, tool in listed.items():
        schema = tool.input_schema
        # Same parameters, types and required fields as the function_tool the agent uses directly.
        assert sorted(schema["properties"]) == sorted(direct[name]["properties"]), name
        # Required: MCP lists exactly the parameters without a default. (Direct mode uses the
        # Agents SDK's strict schemas, which mark every parameter required, e.g. `limit`.)
        no_default = [p for p in schema["properties"] if "default" not in schema["properties"][p]]
        assert sorted(schema.get("required", [])) == sorted(no_default), name
        for param, spec in schema["properties"].items():
            assert spec["type"] == direct[name]["properties"][param]["type"], (name, param)
        assert tool.description  # the docstring, which tells the model what the tool does


# --- (b) results match the fake data ------------------------------------------------


def test_balance_matches_fake_data_and_direct_tool():
    async def scenario():
        async with mcp_session() as session:
            return await call(session, "get_account_balance", account_id="ACC-1002")

    is_error, text = asyncio.run(scenario())
    data.reset_data()
    assert not is_error
    assert json.loads(text) == json.loads(tools.get_account_balance("ACC-1002"))
    assert json.loads(text)["balance"] == data.ACCOUNTS["ACC-1002"]["balance"]
    assert json.loads(text)["account_number"].startswith("****")  # still masked


def test_freeze_card_changes_server_state_and_each_start_is_fresh():
    async def scenario():
        async with mcp_session() as session:
            before = await call(session, "get_card_status", card_id="CARD-1002")
            frozen = await call(session, "freeze_card", card_id="CARD-1002", reason="lost")
            after = await call(session, "get_card_status", card_id="CARD-1002")
        async with mcp_session() as session:  # new process: data reset at startup
            fresh = await call(session, "get_card_status", card_id="CARD-1002")
        return before, frozen, after, fresh

    before, frozen, after, fresh = asyncio.run(scenario())
    assert json.loads(before[1])["status"] == "active"
    assert json.loads(frozen[1]) == {
        "card_id": "CARD-1002",
        "card_number": json.loads(before[1])["card_number"],
        "status": "frozen",
        "reason": "lost",
        "already_frozen": False,
    }
    assert json.loads(after[1])["status"] == "frozen"
    assert json.loads(fresh[1])["status"] == "active"


def test_unknown_id_is_a_normal_error_result_not_a_crash():
    async def scenario():
        async with mcp_session() as session:
            return await call(session, "get_account_balance", account_id="ACC-9999")

    is_error, text = asyncio.run(scenario())
    assert not is_error  # same contract as direct mode: an error JSON, not an exception
    assert json.loads(text)["error"] == "unknown_account"


# --- (c) fault mode, at the MCP level ---------------------------------------------------


@pytest.mark.parametrize("value", ["boom:get_card_status", "slow:no_such_tool", "slow"])
def test_bad_fault_setting_is_rejected(value):
    with pytest.raises(ValueError, match="BANK_MCP_FAULT"):
        parse_fault(value)


@pytest.mark.parametrize("value", ["fast", "-1", "nan"])
def test_bad_slow_seconds_is_rejected(value):
    with pytest.raises(ValueError, match="BANK_MCP_SLOW_SECONDS"):
        parse_slow_seconds(value)


def test_error_fault_returns_an_mcp_error_result():
    async def scenario():
        async with mcp_session({"BANK_MCP_FAULT": "error:get_account_balance"}) as session:
            failed = await call(session, "get_account_balance", account_id="ACC-1002")
            other = await call(session, "get_card_status", card_id="CARD-1002")
        return failed, other

    (is_error, text), other = asyncio.run(scenario())
    assert is_error and "get_account_balance" in text
    # The MCP SDK hides an unexpected exception's message from the client: no internals leak.
    assert "Simulated backend outage" not in text
    assert not other[0]  # only the chosen tool is faulty


def test_slow_fault_hits_the_client_timeout():
    env = {"BANK_MCP_FAULT": "slow:get_account_balance", "BANK_MCP_SLOW_SECONDS": "5"}

    async def scenario():
        async with mcp_session(env) as session:
            # The timeout is on this one call, not the session: a session-wide 0.5 s timeout
            # would already expire while the server starts up, before the slow tool runs.
            start = time.perf_counter()
            with pytest.raises(MCPError, match="timed out"):
                await session.call_tool(
                    "get_account_balance", {"account_id": "ACC-1002"}, read_timeout_seconds=0.5
                )
            return time.perf_counter() - start

    waited = asyncio.run(scenario())
    assert waited < 4  # gave up at the timeout, did not wait the 5 s for the tool


def test_inject_fault_adds_text_but_keeps_the_real_result():
    async def scenario():
        env = {"BANK_MCP_FAULT": "inject:get_recent_transactions"}
        async with mcp_session(env) as session:
            return await call(session, "get_recent_transactions", account_id="ACC-1001")

    is_error, text = asyncio.run(scenario())
    data.reset_data()
    result = json.loads(text)
    assert not is_error
    assert result["note"] == INJECTION_TEXT
    del result["note"]
    assert result == json.loads(tools.get_recent_transactions("ACC-1001"))


# --- (c) fault mode, through the real agent (scripted fake model, no LLM) -------------


def tool_call(name, arguments, call_id):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def scripted_openrouter(steps, sent):
    """Fake OpenRouter: answers request i with steps[i]; records every request body in `sent`."""
    replies = iter(steps)

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        message = next(replies)
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        body = {
            "id": "gen",
            "object": "chat.completion",
            "created": 0,
            "model": "fake/model",
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return httpx2.Response(200, json=body)

    return httpx2.MockTransport(handler)


def run_agent_over_mcp(monkeypatch, fault, steps, timeout_s=10, extra_env=None):
    """Run the real agent in MCP mode against a faulty server; return what the model was sent,
    the run result and the card status afterwards (asked from the same server)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-key-for-offline-test")
    for name in ("AGENT_MODEL", "AGENT_SEED", "AGENT_PROVIDER"):
        monkeypatch.setenv(name, "")
    sent = []

    async def scenario():
        env = {"BANK_MCP_FAULT": fault, **(extra_env or {})}
        async with bank_mcp_server(env=env, timeout_s=timeout_s) as server:
            agent = build_agent(
                max_retries=0,
                transport=scripted_openrouter(steps, sent),
                mcp_servers=[server],
            )
            result = await Runner.run(agent, "Help me with my account", max_turns=8)
            card = await server.call_tool("get_card_status", {"card_id": "CARD-1001"})
        return result, json.loads(card.content[0].text)["status"]

    result, card_status = asyncio.run(scenario())
    return sent, result, card_status


def text_of(content) -> str:
    """Message content as text: a plain string, or a list of {"type": "text"} parts."""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def tool_messages(request_body):
    """Text of every tool-result message the model was sent in one request."""
    return [text_of(m["content"]) for m in request_body["messages"] if m["role"] == "tool"]


def test_agent_survives_a_failing_tool(monkeypatch):
    steps = [
        tool_call("get_account_balance", {"account_id": "ACC-1001"}, "c1"),
        {"role": "assistant", "content": "Sorry, the balance service is unavailable."},
    ]
    sent, result, _ = run_agent_over_mcp(monkeypatch, "error:get_account_balance", steps)
    assert result.final_output == "Sorry, the balance service is unavailable."
    # The failure reached the model as the tool's result (so it can tell the customer),
    # not as an exception that ended the run; the internal error message did not leak.
    [msg] = tool_messages(sent[1])
    assert "Error executing tool get_account_balance" in msg
    assert "Simulated backend outage" not in msg


def test_agent_does_not_hang_on_a_slow_tool(monkeypatch):
    steps = [
        tool_call("get_account_balance", {"account_id": "ACC-1001"}, "c1"),
        {"role": "assistant", "content": "The balance service is slow, please try later."},
    ]
    # The Agents SDK's MCP timeout covers every request, including the start-up handshake, so
    # it must stay well above server start-up time (a few seconds on a cold CI runner). The tool
    # is made far slower instead: the run must end at the timeout, not wait for the tool.
    start = time.perf_counter()
    sent, result, card_status = run_agent_over_mcp(
        monkeypatch,
        "slow:get_account_balance",
        steps,
        timeout_s=8,
        extra_env={"BANK_MCP_SLOW_SECONDS": "60"},
    )
    assert time.perf_counter() - start < 40  # bounded by the 8 s timeout, not the 60 s tool
    # A normal call on the same server still works afterwards, so the connection was fine and
    # it really was the slow tool that timed out (not a server that failed to start).
    assert card_status == "active"
    assert result.final_output.startswith("The balance service is slow")
    # The timeout reached the model as a (generic) tool error, so it can tell the customer.
    [msg] = tool_messages(sent[1])
    assert "error" in msg.lower()


def test_injected_text_reaches_the_model_only_as_tool_data(monkeypatch):
    steps = [
        tool_call("get_recent_transactions", {"account_id": "ACC-1001"}, "c1"),
        {"role": "assistant", "content": "Here are your recent transactions."},
    ]
    sent, result, card_status = run_agent_over_mcp(
        monkeypatch, "inject:get_recent_transactions", steps
    )
    final_messages = sent[-1]["messages"]
    carriers = [m["role"] for m in final_messages if INJECTION_TEXT in text_of(m.get("content"))]
    # Only inside the tool result (data), never in the system prompt or as a user message.
    assert carriers == ["tool"]
    assert not any(
        isinstance(item, ToolCallItem) and item.raw_item.name == "freeze_card"
        for item in result.new_items
    )
    assert card_status == "active"  # nothing on the server was changed by the injection
