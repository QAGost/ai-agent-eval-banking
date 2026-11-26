# AI Agent Evaluation Framework — Banking Assistant Demo

A hands-on project in **evaluating AI agents beyond keyword assertions**.
A tool-using support agent for the fictional **Northwind Demo Bank** is the system under test.
Over six labs it gets an evaluation framework that checks *what the agent did*: which tools it
called, with which arguments and in which order, whether it respected safety rules, and how
good its answers are. Checking whether the reply contains a keyword is not enough.

> ⚠️ **Demo only. All data is synthetic.** Northwind Demo Bank is fictional. Every customer,
> account number, card number and transaction in this repo is invented. This is not a real
> banking system and must not be used with real data.

## Roadmap

| Lab | Topic | Status |
|-----|-------|--------|
| 1 | Banking agent, synthetic data, tools, offline tool tests | ✅ Done |
| 2 | Golden test cases & tool-call trajectory evaluation | ⏳ Planned |
| 3 | LLM-as-judge scoring of answer quality | ⏳ Planned |
| 4 | Safety & prompt-injection evaluation | ⏳ Planned |
| 5 | Robustness, repeat runs & model comparison | ⏳ Planned |
| 6 | Reporting & CI integration | ⏳ Planned |

## What's in Lab 1

```
bank_agent/
  data.py       synthetic customers, accounts, transactions, fraud alerts, cards
  tools.py      6 tools (plain functions + @function_tool wrappers), JSON output, masked numbers
  agent.py      builds the agent (OpenAI Agents SDK + OpenRouter) with its safety instructions
run_agent.py    CLI: runs one question, prints the answer and the tool calls made
tests/          offline pytest tests for every tool (no LLM, no API key)
```

Tools: `verify_customer`, `get_account_balance`, `get_recent_transactions`,
`get_fraud_alerts`, `get_card_status`, `freeze_card`. All tools are read-only except
`freeze_card`, which only changes in-memory state.

Test fixtures for later labs:
- Customer `CUST-1002` (code `7390`) has a suspicious **$1,240.00** charge with an open fraud alert.
- Account `ACC-1003` has a transaction memo containing a prompt-injection attempt.

## Setup

Requires **Python 3.13** and a free [OpenRouter](https://openrouter.ai) API key. The key is
only needed for live agent runs, not for the tests.

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # then edit .env and add your key
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then edit .env and add your key
```

`.env` is git-ignored. Never commit your key.

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key | (required for live runs) |
| `AGENT_MODEL` | Model ID on OpenRouter | `openrouter/free` |

## Run the offline tests

```bash
pytest -v
```

These tests never call an LLM and need no API key.

## Lint and format

```bash
ruff check .
ruff format --check .
```

## Run the agent

```bash
python run_agent.py 'I am customer CUST-1002, PIN 7390. Is the $1,240 charge on my account suspicious?'
```

The output shows the agent's final answer, followed by the list of tool calls it made (tool
name and arguments), the run latency and the number of model requests used. Those tool calls
are what later labs evaluate.

> 💸 **API cost:** one question is not one request. Each agent turn is a separate model call,
> so a single run typically uses 2–8 requests (capped by `max_turns=8`). The OpenRouter free
> tier allows about 50 requests/day, so run live checks sparingly. The offline tests use no
> requests at all.

## License

MIT. See [LICENSE](LICENSE).
