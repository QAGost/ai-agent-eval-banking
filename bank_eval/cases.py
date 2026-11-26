"""Evaluation test-case schema and JSONL helpers.

A case describes ONE user prompt and what a correct agent *trajectory* looks like:
which tools must be called (in order), which must not, and with which arguments.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["happy_path", "edge_case", "verification", "safety"]


class EvalCase(BaseModel):
    # Named EvalCase (not TestCase) so pytest does not try to collect it as a test class.
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    category: Category
    prompt: str = Field(min_length=1)
    # Tools that must appear in this order (other calls may happen in between).
    expected_tools: list[str] = []
    # Tools that must not be called at all.
    forbidden_tools: list[str] = []
    # tool name -> arguments that at least one call of that tool must have.
    expected_args: dict[str, dict[str, Any]] = {}
    # Account/card tools are only allowed after a *successful* verify_customer.
    must_verify_first: bool = True
    # Safety cases must pass EVERY run (pass^k gate).
    safety: bool = False
    notes: str = ""
    # Provenance and human approval (see CLAUDE.md: AI-generated cases need approval).
    source: Literal["seed", "generated"] = "generated"
    approved_by: str | None = None
    approved_at: str | None = None

    @property
    def approved(self) -> bool:
        return bool(self.approved_by)


def load_cases(path: str | Path) -> list[EvalCase]:
    """Load cases from a JSONL file (one JSON object per line; blank lines ignored)."""
    path = Path(path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [EvalCase.model_validate_json(line) for line in lines if line.strip()]


def load_raw(path: str | Path) -> list[dict]:
    """Load unvalidated JSON objects (used for AI-generated candidates)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    items = [json.loads(line) for line in lines if line.strip()]
    if not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{path}: every line must be a JSON object")
    return items


def append_case(path: str | Path, case: EvalCase) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(case.model_dump_json(exclude_none=False) + "\n")
