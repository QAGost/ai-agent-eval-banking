"""Offline tests for the banking tools. No LLM calls, no API key needed."""

import json

import pytest

from bank_agent import data, tools


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts with the original in-memory data (freeze_card mutates it)."""
    data.reset_data()
    yield
    data.reset_data()


def call(fn, *args):
    """Call a tool and parse its JSON string result."""
    raw = fn(*args)
    assert isinstance(raw, str), "tools must return JSON strings"
    return json.loads(raw)


ALL_FULL_NUMBERS = [a["number"] for a in data.ACCOUNTS.values()] + [
    c["number"] for c in data.CARDS.values()
]


def assert_no_full_numbers(raw: str):
    for number in ALL_FULL_NUMBERS:
        assert number not in raw, f"full number {number[-4:]} leaked"


# --- verify_customer ---------------------------------------------------------


def test_verify_customer_success():
    r = call(tools.verify_customer, "CUST-1002", "7390")
    assert r["verified"] is True
    assert r["account_ids"] == ["ACC-1002"]
    assert r["card_ids"] == ["CARD-1002"]


def test_verify_customer_wrong_code():
    r = call(tools.verify_customer, "CUST-1002", "0000")
    assert r["verified"] is False
    assert r["error"] == "verification_failed"
    assert "account_ids" not in r  # nothing leaked on failure


def test_verify_customer_unknown_id():
    r = call(tools.verify_customer, "CUST-9999", "1234")
    assert r["verified"] is False
    assert r["error"] == "unknown_customer"


# --- get_account_balance -----------------------------------------------------


def test_get_account_balance_values_and_masking():
    raw = tools.get_account_balance("ACC-1001")
    r = json.loads(raw)
    assert r["balance"] == 3250.75
    assert r["currency"] == "USD"
    assert r["account_number"] == "****4417"
    assert_no_full_numbers(raw)


def test_get_account_balance_unknown_id():
    r = call(tools.get_account_balance, "ACC-0000")
    assert r["error"] == "unknown_account"


# --- get_recent_transactions -------------------------------------------------


def test_get_recent_transactions_newest_first_and_limit():
    r = call(tools.get_recent_transactions, "ACC-1002", 2)
    txns = r["transactions"]
    assert len(txns) == 2
    assert txns[0]["id"] == "TXN-2003"
    assert txns[0]["amount"] == -1240.00


def test_get_recent_transactions_limit_is_clamped():
    assert len(call(tools.get_recent_transactions, "ACC-1002", 0)["transactions"]) == 1
    assert len(call(tools.get_recent_transactions, "ACC-1002", 999)["transactions"]) == 3


def test_get_recent_transactions_contains_injection_memo_as_data():
    # The injection text is returned as plain data; resisting it is tested in later labs.
    txns = call(tools.get_recent_transactions, "ACC-1003", 5)["transactions"]
    assert any("ignore previous instructions" in t["memo"].lower() for t in txns)


def test_get_recent_transactions_unknown_id():
    assert call(tools.get_recent_transactions, "ACC-0000", 5)["error"] == "unknown_account"


# --- get_fraud_alerts --------------------------------------------------------


def test_get_fraud_alerts_open_alert():
    alerts = call(tools.get_fraud_alerts, "ACC-1002")["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["status"] == "open"
    assert alerts[0]["transaction_id"] == "TXN-2003"


def test_get_fraud_alerts_none():
    assert call(tools.get_fraud_alerts, "ACC-1001")["alerts"] == []


def test_get_fraud_alerts_unknown_id():
    assert call(tools.get_fraud_alerts, "ACC-0000")["error"] == "unknown_account"


# --- get_card_status ---------------------------------------------------------


def test_get_card_status_active_and_masked():
    raw = tools.get_card_status("CARD-1001")
    r = json.loads(raw)
    assert r["status"] == "active"
    assert r["card_number"] == "****8821"
    assert_no_full_numbers(raw)


def test_get_card_status_unknown_id():
    assert call(tools.get_card_status, "CARD-0000")["error"] == "unknown_card"


# --- freeze_card -------------------------------------------------------------


def test_freeze_card_changes_state():
    r = call(tools.freeze_card, "CARD-1002", "Customer reported suspicious charge")
    assert r["status"] == "frozen"
    assert r["already_frozen"] is False
    status = call(tools.get_card_status, "CARD-1002")
    assert status["status"] == "frozen"
    assert status["frozen_reason"] == "Customer reported suspicious charge"


def test_freeze_card_twice_is_idempotent():
    call(tools.freeze_card, "CARD-1002", "first")
    r = call(tools.freeze_card, "CARD-1002", "second")
    assert r["already_frozen"] is True
    assert r["reason"] == "first"  # original reason kept


def test_freeze_card_only_affects_that_card():
    call(tools.freeze_card, "CARD-1002", "test")
    assert call(tools.get_card_status, "CARD-1001")["status"] == "active"


def test_freeze_card_unknown_id():
    assert call(tools.freeze_card, "CARD-0000", "test")["error"] == "unknown_card"


def test_reset_data_unfreezes():
    call(tools.freeze_card, "CARD-1002", "test")
    data.reset_data()
    assert call(tools.get_card_status, "CARD-1002")["status"] == "active"


# --- cross-cutting -----------------------------------------------------------


def test_no_tool_output_leaks_full_numbers():
    outputs = [tools.get_account_balance(a) for a in data.ACCOUNTS]
    outputs += [tools.get_card_status(c) for c in data.CARDS]
    outputs += [tools.freeze_card(c, "test") for c in data.CARDS]
    for raw in outputs:
        assert_no_full_numbers(raw)


def test_agent_tool_wrappers_registered():
    names = {t.name for t in tools.ALL_TOOLS}
    assert names == {
        "verify_customer",
        "get_account_balance",
        "get_recent_transactions",
        "get_fraud_alerts",
        "get_card_status",
        "freeze_card",
    }
