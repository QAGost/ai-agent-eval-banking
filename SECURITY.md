# Security Policy

## Scope

This is a **portfolio and demo project**. Northwind Demo Bank is fictional and all data is
synthetic: no real customers, accounts, card numbers or money are involved, and the agent has no
tool that can move money. It must not be used with real banking data.

Reports are still welcome, especially about:
- leaked secrets (API keys, tokens) in the repository or its history,
- weaknesses in the evaluation framework that would let unsafe agent behaviour pass
  (e.g. a check or the safety gate that can be bypassed),
- vulnerable pinned dependencies or CI supply-chain issues.

## Reporting a vulnerability

Please **do not open a public issue with details**. Use GitHub's private reporting instead:
**Security** tab → **Report a vulnerability**. You can expect an initial reply within 7 days.

If that button is not available, open an issue titled "Security contact request" **without any
details**, and the maintainer will arrange a private channel.

## What is in place

| Control | Where |
|---------|-------|
| Secrets only in a git-ignored `.env`; `.env.example` has placeholders | `.gitignore` |
| Secret scan of staged files before every commit | `.githooks/pre-commit`, `devtools/check_secrets.py` |
| Secret scan, lint and offline tests on every push to `main` and every pull request | `.github/workflows/ci.yml` |
| Pinned dependencies plus a full lock file; vulnerability audit (`pip-audit`) on every push to `main`, every pull request and weekly | `requirements*.txt`, CI |
| GitHub Actions pinned to full commit SHAs, read-only token, no persisted credentials | `.github/workflows/ci.yml` |
| Automated update PRs for dependencies and actions | `.github/dependabot.yml` |
| Commits are signed (SSH signing key) and show as Verified on GitHub | git history |
| Tests are blocked from opening network connections or DNS lookups (test fixture); CI has no API key, so it cannot call the LLM | `tests/conftest.py`, CI |
| Agent tools are read-only (except an in-memory card freeze) and return masked numbers | `bank_agent/tools.py` |

Known limitation (deliberate, see the README roadmap): the agent's authorization rules are enforced
by its instructions, not in code. Lab 4 adds code-enforced guardrails and measures the difference.
