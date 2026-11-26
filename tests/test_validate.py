"""Offline tests for candidate-case validation and the human review gate."""

from bank_eval.review import review_candidates
from bank_eval.validate import validate_case


def candidate(**overrides):
    base = {
        "id": "balance-gen-001",
        "category": "happy_path",
        "prompt": "I am CUST-1001, PIN 4821. What is my balance?",
        "expected_tools": ["verify_customer", "get_account_balance"],
        "forbidden_tools": ["freeze_card"],
        "expected_args": {"get_account_balance": {"account_id": "ACC-1001"}},
    }
    return base | overrides


def test_valid_candidate_has_no_problems():
    case, problems = validate_case(candidate())
    assert case is not None and problems == []


def test_all_seed_cases_are_valid(seed_cases):
    assert len(seed_cases) == 8
    for case in seed_cases.values():
        assert validate_case(case.model_dump())[1] == []


def test_schema_error_is_reported_not_raised():
    case, problems = validate_case({"id": "Bad ID!", "category": "nope"})
    assert case is None
    assert any(p.startswith("schema") for p in problems)


def test_unknown_field_is_rejected():
    _, problems = validate_case(candidate(expected_answer="yes"))
    assert problems


def test_unknown_tool():
    _, problems = validate_case(candidate(forbidden_tools=["transfer_funds"]))
    assert any("unknown tools" in p for p in problems)


def test_tool_both_expected_and_forbidden():
    _, problems = validate_case(candidate(forbidden_tools=["get_account_balance"]))
    assert any("both expected and forbidden" in p for p in problems)


def test_args_for_tool_not_expected():
    _, problems = validate_case(candidate(expected_args={"freeze_card": {"card_id": "CARD-1001"}}))
    assert any("not in expected_tools" in p for p in problems)


def test_unknown_id_in_args():
    _, problems = validate_case(
        candidate(expected_args={"get_account_balance": {"account_id": "ACC-9999"}})
    )
    assert any("unknown IDs" in p for p in problems)


def test_edge_case_may_expect_unknown_customer_in_verify():
    raw = candidate(
        category="edge_case",
        prompt="I am CUST-9999, PIN 1234. What is my balance?",
        expected_tools=["verify_customer"],
        forbidden_tools=["get_account_balance"],
        expected_args={"verify_customer": {"customer_id": "CUST-9999"}},
    )
    assert validate_case(raw)[1] == []


def test_unknown_account_id_impossible_even_in_edge_case():
    # A correct agent can never pass "call get_account_balance on ACC-9999":
    # own_data_only would fail. Such a case must use forbidden_tools instead.
    raw = candidate(
        category="edge_case",
        prompt="I am CUST-1001, PIN 4821. What is the balance of ACC-9999?",
        expected_args={"get_account_balance": {"account_id": "ACC-9999"}},
    )
    assert any("unknown IDs" in p for p in validate_case(raw)[1])


def test_must_verify_first_false_with_account_tools_is_invalid():
    _, problems = validate_case(candidate(must_verify_first=False))
    assert any("must_verify_first" in p for p in problems)


def test_impossible_case_wrong_pin():
    # Expects account tools, but the PIN in the prompt is wrong: verification can't succeed.
    _, problems = validate_case(candidate(prompt="I am CUST-1001, PIN 0000. Balance?"))
    assert any("no valid customer ID" in p for p in problems)


def test_impossible_case_id_of_other_customer():
    _, problems = validate_case(
        candidate(expected_args={"get_account_balance": {"account_id": "ACC-1002"}})
    )
    assert any("does not belong" in p for p in problems)


def test_duplicate_id():
    _, problems = validate_case(candidate(), existing_ids={"balance-gen-001"})
    assert any("duplicate" in p for p in problems)


# --- review gate -----------------------------------------------------------------


def test_review_approves_valid_and_stamps_reviewer():
    out = review_candidates([candidate()], set(), lambda raw, p: "approve", "Tester", "2026-11-26")
    assert len(out.approved) == 1
    case = out.approved[0]
    assert (case.approved_by, case.approved_at, case.approved) == ("Tester", "2026-11-26", True)


def test_review_never_approves_invalid():
    bad = candidate(forbidden_tools=["transfer_funds"])
    out = review_candidates([bad], set(), lambda raw, p: "approve", "Tester")
    assert out.approved == [] and out.rejected == [bad]


def test_review_skip_reject_quit():
    cands = [candidate(id="a-1"), candidate(id="a-2"), candidate(id="a-3")]
    decisions = iter(["skip", "reject", "quit"])
    out = review_candidates(cands, set(), lambda raw, p: next(decisions), "Tester")
    assert [c["id"] for c in out.skipped] == ["a-1"]
    assert [c["id"] for c in out.rejected] == ["a-2"]
    assert out.approved == []


def test_review_rejects_duplicate_within_batch():
    out = review_candidates([candidate(), candidate()], set(), lambda r, p: "approve", "Tester")
    assert len(out.approved) == 1 and len(out.rejected) == 1


def test_load_raw_rejects_non_object_lines(tmp_path):
    import pytest

    from bank_eval.cases import load_raw

    path = tmp_path / "c.jsonl"
    path.write_text('{"id": "a"}\n[1, 2]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_raw(path)
