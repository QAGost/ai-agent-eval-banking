# CLAUDE.md — Project rules

AI Agent Evaluation Framework for a demo banking assistant (portfolio project, 6 labs).

## Rules
- Python 3.13 (developed on 3.13.14), OpenAI Agents SDK (`openai-agents`), calling models
  through OpenRouter (OpenAI-compatible API, base URL `https://openrouter.ai/api/v1`).
- All data is synthetic. Fictional bank name "Northwind Demo Bank". No real bank names,
  no real people, no real account or card numbers.
- Secrets: the API key is read from the environment variable `OPENROUTER_API_KEY`,
  loaded from a local `.env` file via python-dotenv. Never hard-code keys. `.env` must be
  in `.gitignore`. `.env.example` contains placeholder values only.
- The model is configurable via env var `AGENT_MODEL` (default: `openrouter/free`).
- Tools are read-only except `freeze_card`, which only changes in-memory state.
- Offline tests must never call the LLM or need an API key.
- Keep code small, readable and commented for a reviewer.
- AI output is non-deterministic. Any live evaluation must support repeated
  runs per test case (configurable, e.g. `RUNS_PER_CASE`, default 5) and report
  pass rates, not single pass/fail. Report both pass@k (passed at least once)
  and pass^k (passed every run); release gates use pass^k-style pass rates,
  and safety cases must pass every run. Record every run (case id, run number,
  tool calls, answer, latency, errors) so results can be compared later.
  Never claim "reliable" in reports; state "N runs per case, pass rate X%".
- Be mindful of API cost and the OpenRouter free tier (50 requests/day):
  live runs only when explicitly asked; offline tests use recorded or
  simulated data.
- AI-generated test cases are candidates, never trusted directly: they must be
  schema-validated, checked against the synthetic data (IDs exist, expectations
  possible), and approved by a human before joining the golden set.

## Workflow (every change)
1. Make the change. For new or changed behaviour, add offline tests
   (or delegate to the `test-writer` subagent in `.claude/agents/`).
2. Run `ruff check .`, `ruff format --check .` and `pytest`; all must pass.
   These assume an activated venv; in a fresh shell use `.venv/Scripts/...`
   (Windows) or `.venv/bin/...` (macOS/Linux).
3. Have the `reviewer` subagent review the diff; fix every "must fix" finding.
4. Only then commit, and only when asked. Never commit `.env` or local settings.

## Layout
- `bank_agent/data.py` — synthetic data + `reset_data()`
- `bank_agent/tools.py` — plain tool functions (tested offline) + `@function_tool` wrappers
- `bank_agent/agent.py` — builds the agent (OpenRouter model, instructions, tools)
- `run_agent.py` — CLI for one live run
- `bank_eval/` — evaluation framework: case schema, validator, review gate, generator agent,
  recorder, runner, trajectory checks, pass@k / pass^k metrics, report
- `golden/seed_cases.jsonl` (unapproved seeds), `golden/cases.jsonl` (approved golden set)
- `generate_cases.py` → `review_cases.py` → `run_eval.py` → `score_runs.py` (CLIs)
- `tests/` — offline pytest tests (`pytest`)
- `.claude/agents/` — Claude Code subagents: `test-writer`, `reviewer`
