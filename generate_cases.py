"""Ask the generator agent to PROPOSE new test cases (uses 1 model request).

Usage:
    python generate_cases.py --count 5 [--focus "verification bypass attempts"]

Writes candidates/<timestamp>.jsonl (plus the raw model output, for the record) and
prints the validation result for each candidate. Nothing is added to the golden set
until you approve it:  python review_cases.py candidates/<timestamp>.jsonl
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bank_eval.cases import load_cases
from bank_eval.generator import ParseError, build_generator_agent, parse_candidates
from bank_eval.validate import validate_case


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--focus", default="", help="optional theme for the new cases")
    p.add_argument("--golden", default="golden/cases.jsonl")
    args = p.parse_args()

    from agents import Runner

    existing = {c.id for c in load_cases(args.golden)}
    request = f"Propose {args.count} new test cases."
    if args.focus:
        request += f" Focus on: {args.focus}."
    if existing:
        request += f" Do not reuse these ids: {sorted(existing)}."

    result = Runner.run_sync(build_generator_agent(), request, max_turns=1)
    raw_text = str(result.final_output)

    out_dir = Path("candidates")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"{stamp}.raw.txt").write_text(raw_text, encoding="utf-8")

    try:
        candidates = parse_candidates(raw_text)
    except ParseError as e:
        print(f"Could not parse generator output: {e}. Raw output: candidates/{stamp}.raw.txt")
        return 1

    path = out_dir / f"{stamp}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for c in candidates:
            f.write(json.dumps(c) + "\n")

    print(f"{len(candidates)} candidates written to {path}\n")
    for c in candidates:
        _, problems = validate_case(c, existing)
        status = "valid" if not problems else "INVALID: " + "; ".join(problems)
        print(f"- {c.get('id', '?')}: {status}")
    print(f"\nNext: python review_cases.py {path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
