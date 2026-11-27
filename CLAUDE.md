# CLAUDE.md — Project rules

AI Agent Evaluation Framework for a demo banking assistant (portfolio project, 6 labs).
Python 3.13, OpenAI Agents SDK (`openai-agents`), models via OpenRouter
(`https://openrouter.ai/api/v1`); one pinned model from env var `AGENT_MODEL` (default `google/gemma-4-31b-it:free`);
sampling settings come from `AGENT_*` env vars and are recorded with every run.

## Rules
- **Synthetic data only.** Fictional "Northwind Demo Bank"; no real banks, people, or
  account/card numbers.
- **Secrets:** `OPENROUTER_API_KEY` comes from a git-ignored `.env` (python-dotenv); never
  hard-code keys. `.env.example` holds placeholders only.
- **Tools** are read-only except `freeze_card` (in-memory state only).
- **Offline tests** never call the LLM, the network, or need an API key.
- **Code:** small, readable, commented for a reviewer.
- **Evaluation:** output is non-deterministic, so live evals run each case repeatedly
  (`RUNS_PER_CASE`, default 5) and report pass rates with pass@k (passed at least once) and
  pass^k (passed every run). Release gates use pass^k; safety cases must pass every run.
  Record every run (case id, run number, tool calls, answer, latency, errors, served
  model). Never claim "reliable": write "N runs per case, pass rate X%".
- **API cost:** OpenRouter free tier is ~50 requests/day. Live runs only when explicitly
  asked; offline tests use recorded or simulated data.
- **AI-generated test cases** are candidates: schema-validated, checked against the
  synthetic data, and human-approved before joining the golden set.
- **Dependencies are pinned.** To upgrade: bump the pin, reinstall, run all checks,
  regenerate `requirements-lock.txt` (`pip freeze`) in the same commit, keeping the
  `; sys_platform == "win32"` markers (pywin32, colorama).
- **Never bypass** the pre-commit hook (`--no-verify`) or commit signing (`--no-gpg-sign`,
  `-c commit.gpgsign=false`). A secret-scan false positive gets `secret-scan: allow` on that
  line with a reason (it exempts the whole line: never on minified JSON/notebooks).

## Workflow (every change)
`main` is protected: changes only via PR with passing checks ("Tests, lint, secret scan",
"Dependency vulnerability audit") and signed commits; no force push. The owner merges.
Commands are one per line (Windows PowerShell 5.1 has no `&&`).

1. **Branch** from an up-to-date `main`: `git switch main`, `git pull --ff-only`,
   `git switch -c <type>/<name>` (`feat/ fix/ docs/ test/ chore/ lab<N>/`).
2. **Change + offline tests** (straightforward tests can go to the `test-writer` subagent).
3. **Checks:** `ruff check .`, `ruff format --check .`, `pytest` (activated venv, or
   `.venv/Scripts/...` on Windows, `.venv/bin/...` on macOS/Linux).
4. **Review, by risk:**
   - Code, tests, CI, dependencies, security → `reviewer` subagent, once per PR. Give it a
     precise scope (files, purpose, risks) and the fresh check results. Re-review only if a
     must-fix changed code substantially.
   - Docs/comments/typos only → careful self-check; no subagent.
   Fix every must-fix finding.
5. **Commit and push only when asked;** never commit `.env` or local settings. The hook (`git config core.hooksPath .githooks`)
   re-runs the secret scan, ruff and pytest. Commits are SSH-signed; if signing fails, the
   "OpenSSH Authentication Agent" service is stopped or the key isn't loaded (owner runs
   `ssh-add`). Push with `git push -u origin <branch>`, then give the owner the PR link
   (`https://github.com/QAGost/ai-agent-eval-banking/pull/new/<branch>`), a title
   `<type>: <summary>` and a short what / why / how-tested description.
6. **After the owner merges** (PR shows "Merged"): `git switch main`, `git pull --ff-only`,
   `git fetch --prune`, `git branch -D <branch>` (`-D` because squash merges look
   unmerged to git). Never merge PRs yourself.

## Session hygiene (token cost)
- One session per PR or lab; after a merge, suggest starting fresh (`/clear`). CLAUDE.md
  and memory carry context over. Use `/compact` at milestones in long sessions.
- Keep tool output small (`-q`, `tail`, targeted reads); prefer direct file edits over
  long inline scripts.

## Layout
- `bank_agent/` — `data.py` (synthetic data, `reset_data()`), `tools.py` (tools + wrappers),
  `agent.py` (agent, OpenRouter model, served-model log)
- `bank_eval/` — case schema, validator, review gate, generator, recorder, runner,
  trajectory checks, pass@k / pass^k metrics, report
- `golden/` — `seed_cases.jsonl` (unapproved seeds), `cases.jsonl` (approved golden set)
- CLIs: `run_agent.py`, `generate_cases.py` → `review_cases.py` → `run_eval.py` → `score_runs.py`
- `tests/` (offline pytest), `devtools/check_secrets.py` + `.githooks/pre-commit`,
  `.github/` (CI, Dependabot), `.claude/agents/` (`reviewer`, `test-writer`)
