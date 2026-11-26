"""Shared fixtures for the offline tests."""

import socket
from pathlib import Path

import pytest

from bank_agent import data
from bank_eval.cases import load_cases
from bank_eval.recorder import load_records

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Offline tests must never reach the network (CLAUDE.md). Fail loudly if one tries.

    Loopback stays allowed: asyncio on Windows uses a local socket pair internally.
    """
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"Network access blocked in offline tests: {address!r}")
        return real_connect(self, address)

    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        # Async clients may connect without socket.connect, but every host name needs DNS.
        if host not in _LOCAL_HOSTS and host is not None:
            raise RuntimeError(f"Network access blocked in offline tests: DNS lookup {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts with the original in-memory data (freeze_card mutates it)."""
    data.reset_data()
    yield
    data.reset_data()


@pytest.fixture
def seed_cases():
    return {c.id: c for c in load_cases(ROOT / "golden" / "seed_cases.jsonl")}


@pytest.fixture
def recorded_runs():
    """Hand-built recorded runs (see tests/fixtures/recorded_runs.jsonl), keyed by (case, run)."""
    return {(r.case_id, r.run): r for r in load_records(FIXTURES / "recorded_runs.jsonl")}
