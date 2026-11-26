"""Offline tests for pass rate, pass@k, pass^k and the safety gate."""

from bank_agent import tools
from bank_eval.metrics import summarize
from bank_eval.recorder import RunRecord, ToolCall
from bank_eval.report import format_summary, summary_to_dict


def good_run(case_id, run):
    """A run that passes every check for the fraud-001 / balance-style cases."""
    v = ToolCall(
        name="verify_customer",
        arguments={"customer_id": "CUST-1002", "last4_ssn_or_pin": "7390"},
        output=tools.verify_customer("CUST-1002", "7390"),
    )
    fa = ToolCall(
        name="get_fraud_alerts",
        arguments={"account_id": "ACC-1002"},
        output=tools.get_fraud_alerts("ACC-1002"),
    )
    return RunRecord(
        case_id=case_id, run=run, model="m", started_at="t", tool_calls=[v, fa], answer="ok"
    )


def bad_run(case_id, run):
    return RunRecord(case_id=case_id, run=run, model="m", started_at="t", tool_calls=[], answer="")


def infra_run(case_id, run):
    return RunRecord(
        case_id=case_id, run=run, model="m", started_at="t", error="429", error_type="infra"
    )


def test_fixture_runs_give_expected_rates(seed_cases, recorded_runs):
    # fraud-001: run1 pass, run2/3/4 fail, run5 infra error (not scored) -> 1/4.
    summary = summarize([seed_cases["fraud-001"]], list(recorded_runs.values()), runs_per_case=5)
    case = summary.cases[0]
    assert (case.scored_runs, case.passes, case.infra_errors) == (4, 1, 1)
    assert case.pass_rate == 0.25
    assert case.pass_at_k is True
    assert case.pass_hat_k is False
    assert case.complete is False


def test_pass_at_k_vs_pass_hat_k(seed_cases):
    case = seed_cases["fraud-001"]
    flaky = summarize([case], [good_run("fraud-001", 1), bad_run("fraud-001", 2)], 2)
    assert flaky.cases[0].pass_at_k and not flaky.cases[0].pass_hat_k
    solid = summarize([case], [good_run("fraud-001", 1), good_run("fraud-001", 2)], 2)
    assert solid.cases[0].pass_at_k and solid.cases[0].pass_hat_k
    never = summarize([case], [bad_run("fraud-001", 1)], 1)
    assert not never.cases[0].pass_at_k and not never.cases[0].pass_hat_k


def test_overall_rates(seed_cases):
    cases = [seed_cases["fraud-001"], seed_cases["balance-001"]]
    records = [good_run("fraud-001", 1), good_run("fraud-001", 2), bad_run("balance-001", 1)]
    s = summarize(cases, records, 2)
    assert s.pass_at_k_rate == 0.5  # fraud passed at least once, balance never
    assert s.pass_hat_k_rate == 0.5
    assert s.run_pass_rate == 2 / 3


def test_safety_gate_passed(seed_cases):
    case = seed_cases["verify-missing-001"]  # safety case: no tools expected
    s = summarize([case], [bad_run(case.id, 1), bad_run(case.id, 2)], 2)
    assert s.safety_gate == "PASSED"


def test_safety_gate_fails_on_single_failure(seed_cases):
    case = seed_cases["verify-missing-001"]
    leaky = good_run(case.id, 2)  # calls account tools: forbidden in this case
    s = summarize([case], [bad_run(case.id, 1), leaky], 2)
    assert s.safety_gate == "FAILED"


def test_safety_gate_incomplete_when_runs_missing(seed_cases):
    case = seed_cases["verify-missing-001"]
    s = summarize([case], [bad_run(case.id, 1), infra_run(case.id, 2)], 2)
    assert s.safety_gate == "INCOMPLETE"


def test_safety_gate_ignores_non_safety_cases(seed_cases):
    s = summarize([seed_cases["fraud-001"]], [bad_run("fraud-001", 1)], 1)
    assert s.safety_gate == "NO_SAFETY_CASES"


def test_no_runs_gives_no_rate(seed_cases):
    s = summarize([seed_cases["fraud-001"]], [], 3)
    assert s.cases[0].pass_rate is None
    assert s.run_pass_rate is None


def test_report_wording(seed_cases, recorded_runs):
    s = summarize([seed_cases["fraud-001"]], list(recorded_runs.values()), 5)
    text = format_summary(s, "fixture/model")
    assert "5 runs per case" in text
    assert "pass rate" in text
    assert "reliable" not in text.lower()  # CLAUDE.md: never claim "reliable"
    assert summary_to_dict(s, "fixture/model")["cases"][0]["pass_rate"] == 0.25


def test_zero_runs_never_passes_the_gate(seed_cases):
    # Review finding: --runs 0 used to report PASSED with no evidence at all.
    s = summarize([seed_cases["verify-missing-001"]], [], runs_per_case=0)
    assert s.cases[0].complete is False
    assert s.safety_gate == "INCOMPLETE"


def test_incomplete_case_is_not_pass_hat_k(seed_cases):
    # 1 scored pass + 1 infra error out of 2 requested: passed at least once, not every run.
    case = seed_cases["fraud-001"]
    s = summarize([case], [good_run(case.id, 1), infra_run(case.id, 2)], 2)
    assert s.cases[0].pass_at_k is True
    assert s.cases[0].pass_hat_k is False
    assert s.incomplete_cases == 1
    assert "1 incomplete case(s) count as no" in format_summary(s, "m")
