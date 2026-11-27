"""Offline tests for the pinned model and its recorded sampling settings.

No network, no LLM: the end-to-end test uses a fake OpenRouter (httpx2 MockTransport) and
checks the settings really go out in the request body and come back in the run record.
"""

import asyncio
import json

import httpx2
import pytest

from bank_agent.agent import (
    DEFAULT_MODEL,
    ServedModelLog,
    build_agent,
    model_config_from_env,
    model_settings,
)
from bank_eval.recorder import load_records
from bank_eval.runner import make_live_executor, run_eval

ENV_VARS = [
    "AGENT_MODEL",
    "AGENT_TEMPERATURE",
    "AGENT_TOP_P",
    "AGENT_MAX_TOKENS",
    "AGENT_SEED",
    "AGENT_PROVIDER",
]


@pytest.fixture
def clean_env(monkeypatch):
    """Empty values (not unset): load_dotenv() never overrides an existing variable, so the
    developer's own .env cannot leak into these tests. Empty means "use the default"."""
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    return monkeypatch


def test_defaults_pin_one_free_model(clean_env):
    config = model_config_from_env()
    assert config == {
        "model": DEFAULT_MODEL,
        "temperature": 0.3,
        "top_p": 1.0,
        "max_tokens": 1024,
        "seed": None,
        "provider": None,
    }
    assert config["model"] != "openrouter/free"  # a router would defeat the pinning
    assert config["model"].endswith(":free")


def test_env_overrides(clean_env):
    clean_env.setenv("AGENT_MODEL", "vendor/other:free")
    clean_env.setenv("AGENT_TEMPERATURE", "0")
    clean_env.setenv("AGENT_MAX_TOKENS", "256")
    clean_env.setenv("AGENT_SEED", "7")
    clean_env.setenv("AGENT_PROVIDER", "SomeProvider")
    config = model_config_from_env()
    assert config["model"] == "vendor/other:free"
    assert config["temperature"] == 0.0
    assert config["max_tokens"] == 256 and isinstance(config["max_tokens"], int)
    assert config["seed"] == 7
    assert config["provider"] == "SomeProvider"


def test_bad_number_fails_clearly(clean_env):
    clean_env.setenv("AGENT_MAX_TOKENS", "lots")
    with pytest.raises(RuntimeError, match="AGENT_MAX_TOKENS"):
        model_config_from_env()


def test_settings_without_seed_or_provider(clean_env):
    settings = model_settings(model_config_from_env())
    assert (settings.temperature, settings.top_p, settings.max_tokens) == (0.3, 1.0, 1024)
    # Always require providers to honour every setting; no seed / provider pin by default.
    assert settings.extra_body == {"provider": {"require_parameters": True}}


def test_settings_with_seed_and_provider_pin(clean_env):
    clean_env.setenv("AGENT_SEED", "7")
    clean_env.setenv("AGENT_PROVIDER", "SomeProvider")
    settings = model_settings(model_config_from_env())
    assert settings.extra_body == {
        "seed": 7,
        "provider": {
            "require_parameters": True,
            "order": ["SomeProvider"],
            "allow_fallbacks": False,
        },
    }


def test_hook_records_provider_when_reported():
    log = ServedModelLog()
    request = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    body = json.dumps({"model": "vendor/x:free", "provider": "SomeProvider"}).encode()
    resp = httpx2.Response(
        200, request=request, content=body, headers={"content-type": "application/json"}
    )
    asyncio.run(log.on_response(resp))
    assert log.take() == ["vendor/x:free via SomeProvider"]


def test_old_records_without_settings_still_load(tmp_path):
    old = {"case_id": "c", "run": 1, "model": "m", "started_at": "t"}
    (tmp_path / "runs.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert load_records(tmp_path / "runs.jsonl")[0].model_settings == {}


def test_settings_are_sent_and_recorded_end_to_end(tmp_path, seed_cases, clean_env):
    clean_env.setenv("OPENROUTER_API_KEY", "dummy-key-for-offline-test")
    clean_env.setenv("AGENT_SEED", "7")
    sent = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "gen-1",
                "object": "chat.completion",
                "created": 0,
                "model": DEFAULT_MODEL,
                "provider": "SomeProvider",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Please verify first."},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    log = ServedModelLog()
    agent = build_agent(max_retries=0, served_models=log, transport=httpx2.MockTransport(handler))
    config = model_config_from_env()
    run_eval(
        [seed_cases["verify-wrong-pin-001"]],
        1,
        make_live_executor(agent),
        tmp_path / "runs.jsonl",
        config["model"],
        lambda _: None,
        log,
        model_settings=config,
    )

    # What went over the wire: the pinned model and every recorded setting.
    body = sent[0]
    assert body["model"] == DEFAULT_MODEL
    assert (body["temperature"], body["top_p"], body["max_tokens"]) == (0.3, 1.0, 1024)
    assert body["seed"] == 7
    assert body["provider"] == {"require_parameters": True}

    # What was recorded: the same settings, and the model + provider that served it.
    record = load_records(tmp_path / "runs.jsonl")[0]
    assert record.model_settings == config
    assert record.served_models == [f"{DEFAULT_MODEL} via SomeProvider"]
