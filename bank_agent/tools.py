"""Banking tools.

Each tool has two layers:
1. A plain Python function (tested offline, no LLM needed) that returns a JSON string.
2. A `@function_tool` wrapper (bottom of file) that exposes it to the agent.

Design rules:
- Read-only, except `freeze_card`, which only changes in-memory state.
- Account and card numbers are always masked (e.g. "****4417").
- Unknown IDs return an error JSON instead of raising.
"""

import json

from agents import function_tool

from bank_agent import data

MAX_TRANSACTIONS = 20


def _mask(number: str) -> str:
    """Show only the last 4 digits."""
    return "****" + number[-4:]


def _error(code: str, message: str) -> str:
    return json.dumps({"error": code, "message": message})


def verify_customer(customer_id: str, last4_ssn_or_pin: str) -> str:
    """Check the customer's identity with their customer ID and the last 4 SSN digits or PIN."""
    customer = data.CUSTOMERS.get(customer_id)
    if customer is None:
        return json.dumps(
            {
                "verified": False,
                "error": "unknown_customer",
                "message": f"No customer found with id '{customer_id}'",
            }
        )
    if str(last4_ssn_or_pin).strip() != customer["verification_code"]:
        return json.dumps(
            {
                "verified": False,
                "error": "verification_failed",
                "message": "The verification code does not match.",
            }
        )
    return json.dumps(
        {
            "verified": True,
            "customer_id": customer_id,
            "name": customer["name"],
            "account_ids": customer["account_ids"],
            "card_ids": customer["card_ids"],
        }
    )


def get_account_balance(account_id: str) -> str:
    """Return the current balance of an account (account number masked)."""
    account = data.ACCOUNTS.get(account_id)
    if account is None:
        return _error("unknown_account", f"No account found with id '{account_id}'")
    return json.dumps(
        {
            "account_id": account_id,
            "account_number": _mask(account["number"]),
            "type": account["type"],
            "currency": account["currency"],
            "balance": account["balance"],
        }
    )


def get_recent_transactions(account_id: str, limit: int = 5) -> str:
    """Return the most recent transactions for an account, newest first (limit 1-20)."""
    if account_id not in data.ACCOUNTS:
        return _error("unknown_account", f"No account found with id '{account_id}'")
    limit = max(1, min(int(limit), MAX_TRANSACTIONS))  # clamp to a sane range
    txns = data.TRANSACTIONS.get(account_id, [])[:limit]
    return json.dumps({"account_id": account_id, "transactions": txns})


def get_fraud_alerts(account_id: str) -> str:
    """Return fraud alerts (open and closed) for an account."""
    if account_id not in data.ACCOUNTS:
        return _error("unknown_account", f"No account found with id '{account_id}'")
    return json.dumps({"account_id": account_id, "alerts": data.FRAUD_ALERTS.get(account_id, [])})


def get_card_status(card_id: str) -> str:
    """Return the status of a card (active or frozen), card number masked."""
    card = data.CARDS.get(card_id)
    if card is None:
        return _error("unknown_card", f"No card found with id '{card_id}'")
    return json.dumps(
        {
            "card_id": card_id,
            "card_number": _mask(card["number"]),
            "status": card["status"],
            "frozen_reason": card["frozen_reason"],
        }
    )


def freeze_card(card_id: str, reason: str) -> str:
    """Freeze a card. Only use when the customer explicitly asks. Changes in-memory state only."""
    card = data.CARDS.get(card_id)
    if card is None:
        return _error("unknown_card", f"No card found with id '{card_id}'")
    already_frozen = card["status"] == "frozen"
    if not already_frozen:
        card["status"] = "frozen"
        card["frozen_reason"] = reason
    return json.dumps(
        {
            "card_id": card_id,
            "card_number": _mask(card["number"]),
            "status": "frozen",
            "reason": card["frozen_reason"],
            "already_frozen": already_frozen,
        }
    )


# --- Agent-facing wrappers --------------------------------------------------
# function_tool reads the name, type hints and docstring to build the tool schema.
# Wrapping (instead of decorating) keeps the plain functions directly testable.
ALL_TOOLS = [
    function_tool(verify_customer),
    function_tool(get_account_balance),
    function_tool(get_recent_transactions),
    function_tool(get_fraud_alerts),
    function_tool(get_card_status),
    function_tool(freeze_card),
]
