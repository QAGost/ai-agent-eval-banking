"""Human-readable and JSON reports.

Wording rule (CLAUDE.md): never claim "reliable"; always state "N runs per case, pass rate X%".
"""

from bank_eval.metrics import EvalSummary


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def format_summary(summary: EvalSummary, model: str) -> str:
    k = summary.runs_per_case
    served = ", ".join(f"{m} x{n}" for m, n in summary.served_models.most_common())
    lines = [
        f"Model: {model}",
        f"Served by (requests per model): {served or 'not recorded'}",
        (
            f"{k} runs per case requested, {len(summary.cases)} cases, "
            f"{summary.scored_runs} runs scored, pass rate {_pct(summary.run_pass_rate)}"
        ),
        "",
        (
            f"{'case':<30}{'category':<14}{'scored':>7}{'passed':>8}{'rate':>7}"
            f"{'pass@k':>8}{'pass^k':>8}  failed checks / notes"
        ),
    ]
    for c in summary.cases:
        notes = ", ".join(f"{name} x{n}" for name, n in c.failed_checks.most_common())
        if c.infra_errors:
            notes += f"{'; ' if notes else ''}{c.infra_errors} infra error(s), not scored"
        if not c.complete:
            notes += f"{'; ' if notes else ''}INCOMPLETE ({c.scored_runs}/{k})"
        label = c.case_id + (" [safety]" if c.safety else "")
        lines.append(
            f"{label:<30}{c.category:<14}{c.scored_runs:>7}{c.passes:>8}{_pct(c.pass_rate):>7}"
            f"{'yes' if c.pass_at_k else 'no':>8}{'yes' if c.pass_hat_k else 'no':>8}  {notes}"
        )
    lines += [
        "",
        f"pass@{k}: {_pct(summary.pass_at_k_rate)} of cases passed at least once",
        f"pass^{k}: {_pct(summary.pass_hat_k_rate)} of cases passed all {k} runs"
        + (
            f" ({summary.incomplete_cases} incomplete case(s) count as no)"
            if summary.incomplete_cases
            else ""
        ),
        f"Safety gate (every safety case passes every run): {summary.safety_gate}",
    ]
    return "\n".join(lines)


def summary_to_dict(summary: EvalSummary, model: str) -> dict:
    return {
        "model": model,
        "served_models": dict(summary.served_models),
        "runs_per_case": summary.runs_per_case,
        "run_pass_rate": summary.run_pass_rate,
        "pass_at_k_rate": summary.pass_at_k_rate,
        "pass_hat_k_rate": summary.pass_hat_k_rate,
        "scored_runs": summary.scored_runs,
        "incomplete_cases": summary.incomplete_cases,
        "safety_gate": summary.safety_gate,
        "cases": [
            {
                "case_id": c.case_id,
                "category": c.category,
                "safety": c.safety,
                "runs_requested": c.runs_requested,
                "scored_runs": c.scored_runs,
                "passes": c.passes,
                "pass_rate": c.pass_rate,
                "pass_at_k": c.pass_at_k,
                "pass_hat_k": c.pass_hat_k,
                "complete": c.complete,
                "infra_errors": c.infra_errors,
                "failed_checks": dict(c.failed_checks),
            }
            for c in summary.cases
        ],
    }
