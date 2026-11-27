"""Run the live evaluation: every approved golden case, N runs each.

Usage:
    python run_eval.py --runs 2 --case fraud-001        # small, free-tier friendly
    python run_eval.py                                  # all cases, RUNS_PER_CASE runs (default 5)

Prints a request estimate and asks before spending anything (skip with --yes).
Results go to results/<timestamp>/: runs.jsonl (every run), cases.jsonl (case snapshot),
meta.json and summary.json. Re-score later with: python score_runs.py results/<timestamp>
Exit code 1 if the safety gate fails or is incomplete, so CI can use it later.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from bank_eval.cases import append_case, load_cases
from bank_eval.metrics import summarize
from bank_eval.report import format_summary, summary_to_dict
from bank_eval.runner import estimate_requests, make_live_executor, run_eval

load_dotenv()  # so RUNS_PER_CASE / AGENT_MODEL in .env are honoured


def ask_yes_no(prompt: str) -> bool:
    """True only on an explicit 'y'. No terminal or no input (EOF) means no."""
    try:
        return sys.stdin.isatty() and input(prompt).strip().lower() == "y"
    except EOFError:
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--runs", type=int, default=int(os.getenv("RUNS_PER_CASE", "5")))
    p.add_argument("--case", action="append", help="case id to run (repeatable); default: all")
    p.add_argument("--cases", default="golden/cases.jsonl", help="golden cases file")
    p.add_argument("--out", default="results", help="results root folder")
    p.add_argument("--yes", action="store_true", help="skip the budget confirmation")
    args = p.parse_args()
    if args.runs < 1:
        p.error("--runs / RUNS_PER_CASE must be at least 1")

    cases = load_cases(args.cases)
    unapproved = [c.id for c in cases if not c.approved]
    if unapproved:
        print(f"Skipping unapproved cases (approve them with review_cases.py): {unapproved}")
    cases = [c for c in cases if c.approved]
    if args.case:
        missing = set(args.case) - {c.id for c in cases}
        if missing:
            print(f"Unknown or unapproved case ids: {sorted(missing)}")
            return 2
        cases = [c for c in cases if c.id in args.case]
    if not cases:
        print(
            "No approved cases to run. Review seeds first: python review_cases.py golden/seed_cases.jsonl"
        )
        return 2

    est = estimate_requests(len(cases), args.runs)
    print(
        f"{len(cases)} cases x {args.runs} runs = {len(cases) * args.runs} agent runs, "
        f"roughly {est} model requests (free tier: about 50/day)."
    )
    confirmed = args.yes or ask_yes_no("Proceed? [y/N] ")
    if not confirmed:
        print("Aborted. Nothing was sent.")
        return 1

    # Only needed for live runs.
    from bank_agent.agent import ServedModelLog, build_agent, model_config_from_env

    # Build first: a missing key fails here, before an empty results folder is created.
    # One config for both the agent and the records, so what is recorded is what was used.
    config = model_config_from_env()
    model = config["model"]
    served_log = ServedModelLog()
    agent = build_agent(max_retries=0, served_models=served_log, config=config)
    executor = make_live_executor(agent)
    out_dir = Path(args.out) / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True)
    for case in cases:  # snapshot the exact cases used, so re-scoring is reproducible
        append_case(out_dir / "cases.jsonl", case)
    meta = {
        "model": model,
        "model_settings": config,
        "runs_per_case": args.runs,
        "case_ids": [c.id for c in cases],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    records = run_eval(
        cases,
        args.runs,
        executor,
        out_dir / "runs.jsonl",
        model,
        served_log=served_log,
        model_settings=config,
    )

    summary = summarize(cases, records, args.runs)
    print()
    print(format_summary(summary, model))
    (out_dir / "summary.json").write_text(
        json.dumps(summary_to_dict(summary, model), indent=2), encoding="utf-8"
    )
    print(f"\nSaved to {out_dir}")
    return 0 if summary.safety_gate in ("PASSED", "NO_SAFETY_CASES") else 1


if __name__ == "__main__":
    sys.exit(main())
