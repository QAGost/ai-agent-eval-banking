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

## Layout
- `bank_agent/data.py` — synthetic data + `reset_data()`
- `bank_agent/tools.py` — plain tool functions (tested offline) + `@function_tool` wrappers
- `bank_agent/agent.py` — builds the agent (OpenRouter model, instructions, tools)
- `run_agent.py` — CLI for one live run
- `tests/` — offline pytest tests (`pytest`)
