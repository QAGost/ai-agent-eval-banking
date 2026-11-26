"""Shared fixtures for the offline tests."""

from pathlib import Path

import pytest

from bank_agent import data
from bank_eval.cases import load_cases
from bank_eval.recorder import load_records

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts with the original in-memory data (freeze_card mutates it)."""
    data.reset_data()
    yield
    data.reset_data()


@pytest.fixture
def seed_cases():
    return {c.id: c for c in load_cases(ROOT / "golden" / "seed_cases.jsonl")}


@pytest.fixture
def recorded_runs():
    """Hand-built recorded runs (see tests/fixtures/recorded_runs.jsonl), keyed by (case, run)."""
    return {(r.case_id, r.run): r for r in load_records(FIXTURES / "recorded_runs.jsonl")}
