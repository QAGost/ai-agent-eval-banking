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

## Layout
- `bank_agent/data.py` — synthetic data + `reset_data()`
- `bank_agent/tools.py` — plain tool functions (tested offline) + `@function_tool` wrappers
- `bank_agent/agent.py` — builds the agent (OpenRouter model, instructions, tools)
- `run_agent.py` — CLI for one live run
- `tests/` — offline pytest tests (`pytest`)
