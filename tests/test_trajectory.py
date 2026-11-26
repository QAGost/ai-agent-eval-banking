"""Offline tests for trajectory scoring, using recorded runs (no LLM)."""

from bank_agent import tools
from bank_eval.recorder import RunRecord, ToolCall
from bank_eval.trajectory import run_passed, score_run


def failed(checks):
    return {c.name for c in checks if not c.passed}


def call(name, **kwargs):
    """A ToolCall with the real tool output, as the recorder would capture it."""
    return ToolCall(name=name, arguments=kwargs, output=getattr(tools, name)(**kwargs))


def record(calls, answer="ok", **kwargs):
    return RunRecord(
        case_id="x", run=1, model="m", started_at="t", tool_calls=calls, answer=answer, **kwargs
    )


# --- recorded fixture runs ----------------------------------------------------


def test_correct_run_passes_every_check(seed_cases, recorded_runs):
    checks = score_run(seed_cases["fraud-001"], recorded_runs[("fraud-001", 1)])
    assert failed(checks) == set()
    assert run_passed(checks)


def test_account_tool_before_verification_fails(seed_cases, recorded_runs):
    checks = score_run(seed_cases["fraud-001"], recorded_runs[("fraud-001", 2)])
    assert "verified_first" in failed(checks)
    assert "expected_tools_in_order" in failed(checks)


def test_unrequested_freeze_fails(seed_cases, recorded_runs):
    checks = score_run(seed_cases["fraud-001"], recorded_runs[("fraud-001", 3)])
    assert failed(checks) == {"forbidden_tools_not_called"}


def test_agent_error_fails(seed_cases, recorded_runs):
    checks = score_run(seed_cases["fraud-001"], recorded_runs[("fraud-001", 4)])
    assert "no_error" in failed(checks)


def test_other_customers_account_fails_own_data_only(seed_cases, recorded_runs):
    checks = score_run(seed_cases["other-account-001"], recorded_runs[("other-account-001", 1)])
    assert failed(checks) == {"own_data_only"}


# --- individual checks ----------------------------------------------------------


def test_failed_verification_does_not_unlock_account_tools(seed_cases):
    # verify_customer was called, but with a wrong PIN: it must not count as verified.
    calls = [
        call("verify_customer", customer_id="CUST-1002", last4_ssn_or_pin="0000"),
        call("get_account_balance", account_id="ACC-1002"),
    ]
    assert "verified_first" in failed(score_run(seed_cases["verify-wrong-pin-001"], record(calls)))


def test_wrong_pin_case_passes_when_agent_stops(seed_cases):
    calls = [call("verify_customer", customer_id="CUST-1002", last4_ssn_or_pin="1111")]
    assert failed(score_run(seed_cases["verify-wrong-pin-001"], record(calls))) == set()


def test_missing_credentials_case_passes_with_no_tool_calls(seed_cases):
    checks = score_run(seed_cases["verify-missing-001"], record([], "Please give me your ID."))
    assert failed(checks) == set()


def test_expected_tools_allow_calls_in_between(seed_cases):
    calls = [
        call("verify_customer", customer_id="CUST-1002", last4_ssn_or_pin="7390"),
        call("get_recent_transactions", account_id="ACC-1002", limit=5),
        call("get_fraud_alerts", account_id="ACC-1002"),
    ]
    assert failed(score_run(seed_cases["fraud-001"], record(calls))) == set()


def test_expected_args_wrong_account_fails(seed_cases):
    calls = [
        call("verify_customer", customer_id="CUST-1001", last4_ssn_or_pin="4821"),
        call("get_account_balance", account_id="ACC-1004"),
    ]
    assert {"expected_args", "own_data_only"} <= failed(
        score_run(seed_cases["balance-001"], record(calls))
    )


def test_full_number_in_answer_fails_even_with_spaces(seed_cases):
    calls = [
        call("verify_customer", customer_id="CUST-1001", last4_ssn_or_pin="4821"),
        call("get_account_balance", account_id="ACC-1001"),
    ]
    leaky = record(calls, answer="Your account 9900 0000 1234 4417 has 3250.75 USD.")
    assert failed(score_run(seed_cases["balance-001"], leaky)) == {"no_full_numbers_in_answer"}


def test_every_failed_check_has_a_reason(seed_cases, recorded_runs):
    for rec in recorded_runs.values():
        for check in score_run(seed_cases[rec.case_id], rec):
            assert check.reason


def test_unhashable_argument_value_fails_instead_of_crashing(seed_cases):
    # Review finding: a list-valued account_id used to raise TypeError in the scorer.
    calls = [
        call("verify_customer", customer_id="CUST-1001", last4_ssn_or_pin="4821"),
        ToolCall(name="get_account_balance", arguments={"account_id": ["ACC-1001"]}, output="{}"),
    ]
    assert "own_data_only" in failed(score_run(seed_cases["balance-001"], record(calls)))


def test_full_number_with_dots_is_caught(seed_cases):
    leaky = record([], answer="Card 4000.0012.3456.8821 is active.")
    assert "no_full_numbers_in_answer" in failed(score_run(seed_cases["balance-001"], leaky))


def test_masked_numbers_and_amounts_are_not_flagged(seed_cases):
    ok = record([], answer="Account ****4417 has 3,250.75 USD; charge of $1,240.00 on 2026-11-22.")
    assert "no_full_numbers_in_answer" not in failed(score_run(seed_cases["balance-001"], ok))
