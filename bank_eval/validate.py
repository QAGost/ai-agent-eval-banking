"""Deterministic validation of candidate test cases (no LLM).

AI-generated cases are only candidates. Before a human even looks at one, it must:
- match the schema,
- use only tools that exist,
- not contradict itself (a tool both expected and forbidden),
- reference only IDs that exist in the synthetic data,
- be *possible*: if account tools are expected, the prompt must contain valid credentials
  for the customer who owns the referenced IDs.
"""

import re

from pydantic import ValidationError

from bank_agent import data
from bank_eval.cases import EvalCase
from bank_eval.trajectory import ACCOUNT_TOOLS, ALL_TOOL_NAMES

_ID_PATTERN = re.compile(r"\b(?:CUST|ACC|CARD)-\d+\b")
_KNOWN_IDS = set(data.CUSTOMERS) | set(data.ACCOUNTS) | set(data.CARDS)


def _owner(entity_id: str) -> str | None:
    """Customer ID that owns an account/card ID (or the customer ID itself)."""
    if entity_id in data.CUSTOMERS:
        return entity_id
    record = data.ACCOUNTS.get(entity_id) or data.CARDS.get(entity_id)
    return record["customer_id"] if record else None


def _credentials_in_prompt(prompt: str) -> set[str]:
    """Customers whose ID AND correct verification code both appear in the prompt."""
    return {
        cid
        for cid, c in data.CUSTOMERS.items()
        if cid in prompt and re.search(rf"\b{c['verification_code']}\b", prompt)
    }


def validate_case(
    raw: dict, existing_ids: set[str] = frozenset()
) -> tuple[EvalCase | None, list[str]]:
    """Return (parsed case or None, list of problems). No problems = valid."""
    try:
        case = EvalCase.model_validate(raw)
    except ValidationError as e:
        return None, [f"schema: {err['loc']}: {err['msg']}" for err in e.errors()]

    problems: list[str] = []
    if case.id in existing_ids:
        problems.append(f"duplicate id: {case.id}")

    used_tools = set(case.expected_tools) | set(case.forbidden_tools) | set(case.expected_args)
    if unknown := sorted(used_tools - ALL_TOOL_NAMES):
        problems.append(f"unknown tools: {unknown}")
    if both := sorted(set(case.expected_tools) & set(case.forbidden_tools)):
        problems.append(f"tools both expected and forbidden: {both}")
    if extra := sorted(set(case.expected_args) - set(case.expected_tools)):
        problems.append(f"expected_args for tools not in expected_tools: {extra}")

    # verify_customer may expect an unknown customer ID in an edge case ("unknown customer").
    verify_args = case.expected_args.get("verify_customer", {})
    verify_ids = [str(v) for v in verify_args.values() if _ID_PATTERN.fullmatch(str(v))]
    unknown_customers = [i for i in verify_ids if i not in _KNOWN_IDS]
    if unknown_customers and case.category != "edge_case":
        problems.append(f"unknown IDs in expected_args: {unknown_customers}")

    # Account/card tools can only succeed on known IDs owned by the verified customer, so an
    # expected call on any other ID is impossible for a correct agent, in every category.
    # (To test an unknown ID, put the tool in forbidden_tools instead.)
    account_args = [
        str(v)
        for tool, args in case.expected_args.items()
        if tool in ACCOUNT_TOOLS
        for v in args.values()
    ]
    unknown_ids = sorted(
        i for i in account_args if _ID_PATTERN.fullmatch(i) and i not in _KNOWN_IDS
    )
    if unknown_ids:
        problems.append(f"unknown IDs in expected_args: {unknown_ids}")

    expects_account_tools = bool(set(case.expected_tools) & ACCOUNT_TOOLS)
    if expects_account_tools and not case.must_verify_first:
        problems.append("must_verify_first=false with account tools expected breaks agent rule 1")

    # Possibility check: expecting account tools requires valid credentials in the prompt,
    # and the expected IDs must belong to that customer.
    if expects_account_tools:
        verified = _credentials_in_prompt(case.prompt)
        if not verified:
            problems.append("account tools expected but prompt has no valid customer ID + code")
        for entity_id in account_args:
            owner = _owner(entity_id)
            if owner and verified and owner not in verified:
                problems.append(f"{entity_id} does not belong to the verified customer")

    return case, problems
