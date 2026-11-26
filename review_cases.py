"""Human approval of candidate test cases (offline, no API calls).

Usage:
    python review_cases.py golden/seed_cases.jsonl
    python review_cases.py candidates/<timestamp>.jsonl [--reviewer "Your Name"]

Shows each candidate with its validation result. Approved cases are appended to
golden/cases.jsonl with approved_by / approved_at. Invalid cases cannot be approved.
Candidates already in the golden set are skipped.
"""

import argparse
import json
import subprocess
import sys

from bank_eval.cases import append_case, load_cases, load_raw
from bank_eval.review import review_candidates

CHOICES = {"a": "approve", "r": "reject", "s": "skip", "q": "quit"}


def default_reviewer() -> str:
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        name = ""
    return name or "unknown"


def ask(raw: dict, problems: list[str]) -> str:
    """Interactive decision for one candidate."""
    print("\n" + "=" * 70)
    print(json.dumps(raw, indent=2))
    if problems:
        print("\nINVALID (cannot be approved):")
        for problem in problems:
            print(f"  - {problem}")
        prompt = "[r]eject / [s]kip / [q]uit: "
    else:
        print("\nValidation: OK")
        prompt = "[a]pprove / [r]eject / [s]kip / [q]uit: "
    while True:
        try:
            answer = input(prompt)
        except EOFError:
            return "quit"
        choice = CHOICES.get(answer.strip().lower()[:1])
        if choice and not (choice == "approve" and problems):
            return choice


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("candidates")
    p.add_argument("--golden", default="golden/cases.jsonl")
    p.add_argument("--reviewer", default=None)
    args = p.parse_args()

    golden = load_cases(args.golden)
    existing = {c.id for c in golden}
    approved_prompts = {(c.id, c.prompt) for c in golden}
    # Skip only candidates already approved (same id AND prompt); a different case reusing
    # an id is still shown, and the validator flags it as a duplicate.
    candidates = [
        c
        for c in load_raw(args.candidates)
        if (c.get("id"), c.get("prompt")) not in approved_prompts
    ]
    if not candidates:
        print("Nothing to review: all candidates are already in the golden set.")
        return 0

    reviewer = args.reviewer or default_reviewer()
    print(f"Reviewing {len(candidates)} candidates as '{reviewer}'.")
    outcome = review_candidates(candidates, existing, ask, reviewer)
    for case in outcome.approved:
        append_case(args.golden, case)
    print(
        f"\nApproved {len(outcome.approved)}, rejected {len(outcome.rejected)}, "
        f"skipped {len(outcome.skipped)}. Golden set: {args.golden}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
