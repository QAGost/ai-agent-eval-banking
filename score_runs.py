"""Re-score a saved evaluation offline (no API calls).

Usage:
    python score_runs.py results/<timestamp>

Uses the case snapshot saved with the run, so a later change to golden/cases.jsonl does
not silently change old results. Useful after improving the scoring checks.
"""

import json
import sys
from pathlib import Path

from bank_eval.cases import load_cases
from bank_eval.metrics import summarize
from bank_eval.recorder import load_records
from bank_eval.report import format_summary


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python score_runs.py results/<timestamp>")
        return 1
    folder = Path(sys.argv[1])
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    cases = load_cases(folder / "cases.jsonl")
    records = load_records(folder / "runs.jsonl")
    summary = summarize(cases, records, meta["runs_per_case"])
    print(format_summary(summary, meta["model"]))
    return 0 if summary.safety_gate in ("PASSED", "NO_SAFETY_CASES") else 1


if __name__ == "__main__":
    sys.exit(main())
