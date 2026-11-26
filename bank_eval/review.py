"""Human review of candidate cases: the gate between "AI proposed" and "golden".

The decision function is injected so the flow can be tested without a keyboard.
Invalid candidates can never be approved.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from bank_eval.cases import EvalCase
from bank_eval.validate import validate_case

# decide(raw_candidate, problems) -> "approve" | "reject" | "skip" | "quit"
Decider = Callable[[dict, list[str]], str]


@dataclass
class ReviewOutcome:
    approved: list[EvalCase] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def review_candidates(
    candidates: list[dict],
    existing_ids: set[str],
    decide: Decider,
    reviewer: str,
    today: str | None = None,
) -> ReviewOutcome:
    outcome = ReviewOutcome()
    seen = set(existing_ids)
    for raw in candidates:
        case, problems = validate_case(raw, seen)
        decision = decide(raw, problems)
        if decision == "quit":
            break
        if decision == "approve" and case is not None and not problems:
            approved = case.model_copy(
                update={"approved_by": reviewer, "approved_at": today or date.today().isoformat()}
            )
            outcome.approved.append(approved)
            seen.add(approved.id)
        elif decision == "skip":
            outcome.skipped.append(raw)
        else:
            # "reject", or "approve" on an invalid case: invalid cases are always rejected.
            outcome.rejected.append(raw)
    return outcome
