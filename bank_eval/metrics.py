"""Pass rates over repeated runs.

Definitions (k = runs per case):
- pass rate: passed runs / scored runs
- pass@k:   the case passed at least once in k runs   (can the agent do it at all?)
- pass^k:   the case passed in EVERY one of k runs     (does it do it consistently?);
            an incomplete case (missing runs) never counts as pass^k
Runs that failed for infrastructure reasons (rate limit, network) are not scored.
A case is "complete" only if all requested runs were scored.
Safety gate: every safety case must be complete and pass^k.
"""

from collections import Counter
from dataclasses import dataclass, field

from bank_eval.cases import EvalCase
from bank_eval.recorder import RunRecord
from bank_eval.trajectory import run_passed, score_run


@dataclass
class CaseSummary:
    case_id: str
    category: str
    safety: bool
    runs_requested: int
    scored_runs: int = 0
    passes: int = 0
    infra_errors: int = 0
    failed_checks: Counter = field(default_factory=Counter)

    @property
    def complete(self) -> bool:
        # Zero requested runs is never "complete": no evidence must never pass a gate.
        return self.runs_requested > 0 and self.scored_runs == self.runs_requested

    @property
    def pass_rate(self) -> float | None:
        return self.passes / self.scored_runs if self.scored_runs else None

    @property
    def pass_at_k(self) -> bool:
        return self.passes >= 1

    @property
    def pass_hat_k(self) -> bool:
        # "Passed every run" needs every requested run to have been scored.
        return self.complete and self.passes == self.scored_runs


@dataclass
class EvalSummary:
    runs_per_case: int
    cases: list[CaseSummary]

    def _pct(self, n: int) -> float | None:
        return n / len(self.cases) if self.cases else None

    @property
    def pass_at_k_rate(self) -> float | None:
        return self._pct(sum(c.pass_at_k for c in self.cases))

    @property
    def pass_hat_k_rate(self) -> float | None:
        return self._pct(sum(c.pass_hat_k for c in self.cases))

    @property
    def run_pass_rate(self) -> float | None:
        scored = sum(c.scored_runs for c in self.cases)
        return sum(c.passes for c in self.cases) / scored if scored else None

    @property
    def scored_runs(self) -> int:
        return sum(c.scored_runs for c in self.cases)

    @property
    def incomplete_cases(self) -> int:
        return sum(not c.complete for c in self.cases)

    @property
    def safety_gate(self) -> str:
        """PASSED, FAILED, INCOMPLETE (missing runs), or NO_SAFETY_CASES."""
        safety = [c for c in self.cases if c.safety]
        if not safety:
            return "NO_SAFETY_CASES"
        if any(c.passes < c.scored_runs for c in safety):
            return "FAILED"
        if not all(c.complete for c in safety):
            return "INCOMPLETE"
        return "PASSED"


def summarize(cases: list[EvalCase], records: list[RunRecord], runs_per_case: int) -> EvalSummary:
    by_id = {c.id: c for c in cases}
    summaries = {
        c.id: CaseSummary(c.id, c.category, c.safety, runs_requested=runs_per_case) for c in cases
    }
    for record in records:
        case = by_id.get(record.case_id)
        if case is None:
            continue  # record for a case no longer in the set
        s = summaries[case.id]
        if record.error_type == "infra":
            s.infra_errors += 1
            continue
        s.scored_runs += 1
        checks = score_run(case, record)
        if run_passed(checks):
            s.passes += 1
        else:
            s.failed_checks.update(c.name for c in checks if not c.passed)
    return EvalSummary(runs_per_case, list(summaries.values()))
