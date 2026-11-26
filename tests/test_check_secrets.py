"""Offline tests for the pre-commit secret scanner.

Fake secrets are assembled from pieces at runtime, so this file itself never contains
a key-shaped string (and passes its own scanner).
"""

import subprocess

import pytest

from devtools.check_secrets import check_filename, main, scan_text

FAKE = {
    "openrouter-key": "sk-or-" + "v1-" + "a1" * 32,
    "anthropic-key": "sk-" + "ant-" + "x" * 30,
    "openai-key": "sk-" + "proj-" + "Ab1" * 12,
    "aws-access-key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "github-token": "ghp" + "_" + "a" * 36,
    "private-key": "-----BEGIN " + "RSA PRIVATE KEY-----",
}


@pytest.mark.parametrize(("rule", "secret"), FAKE.items())
def test_each_rule_detects_its_secret(rule, secret):
    findings = scan_text("f.py", f"x = '{secret}'")
    assert rule in {f.rule for f in findings}
    assert all(secret not in str(f) for f in findings)  # never print the secret


VALUE = "abc123" * 5
KEY = "OPENROUTER_" + "API_KEY"


@pytest.mark.parametrize(
    "line",
    [
        f"{KEY}={VALUE}",  # .env style
        f"{KEY}: {VALUE}",  # YAML
        f'"{KEY}": "{VALUE}"',  # JSON
        f'os.environ["{KEY}"] = "{VALUE}"',  # Python
    ],
)
def test_real_value_assigned_to_key_variable_is_found(line):
    assert [f.rule for f in scan_text("cfg", line)] == ["openrouter-key-assignment"]


@pytest.mark.parametrize(
    "line",
    [
        "OPENROUTER_API_KEY=your-openrouter-api-key-here",  # .env.example placeholder
        'api_key = os.getenv("OPENROUTER_API_KEY")',
        'monkeypatch.setenv("OPENROUTER_API_KEY", "dummy")',
        "Card ****4417, account 9900000012344417",  # synthetic data is not a secret
        "sk-or-v1-short",
    ],
)
def test_placeholder_and_project_text_are_not_flagged(line):
    assert scan_text("x", line) == []


def test_allow_marker_skips_line():
    line = f"token = '{FAKE['aws-access-key']}'  # secret-scan: allow (documented example)"
    assert scan_text("x", line) == []


def test_finding_reports_line_number():
    text = "ok\nok\n" + FAKE["github-token"]
    assert [(f.line, f.rule) for f in scan_text("x", text)] == [(3, "github-token")]


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".ENV",
        "config/.env",
        ".env.local",
        ".env.prod",
        "prod.env",
        ".claude/settings.local.json",
        "certs/server.pem",
        "a.KEY",
    ],
)
def test_forbidden_files(path):
    assert check_filename(path).rule == "forbidden-file"


@pytest.mark.parametrize(
    "path", [".env.example", "README.md", "environment.py", "keys.py", "docs/env.md"]
)
def test_allowed_files(path):
    assert check_filename(path) is None


# --- against a real (temporary, local) git repository -------------------------------


# Set by git while a hook runs (e.g. GIT_INDEX_FILE = the commit being made). If the temp
# repos inherited them, these tests would read/write the REAL commit's index.
GIT_ENV_VARS = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in GIT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    monkeypatch.chdir(tmp_path)
    return tmp_path, git


def test_staged_secret_blocks_commit(repo, capsys):
    path, git = repo
    (path / "app.py").write_text(f"KEY = '{FAKE['openrouter-key']}'\n", encoding="utf-8")
    git("add", "app.py")
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "app.py:1: openrouter-key" in out
    assert FAKE["openrouter-key"] not in out


def test_staged_env_file_blocks_commit(repo):
    path, git = repo
    (path / ".env").write_text("OPENROUTER_API_KEY=your-openrouter-api-key-here\n")
    git("add", "-f", ".env")
    assert main([]) == 1


def test_scans_staged_content_not_working_copy(repo):
    # Secret staged, then removed from the working copy only: still blocked.
    path, git = repo
    f = path / "app.py"
    f.write_text(f"KEY = '{FAKE['aws-access-key']}'\n", encoding="utf-8")
    git("add", "app.py")
    f.write_text("KEY = None\n", encoding="utf-8")
    assert main([]) == 1


def test_clean_stage_passes(repo):
    path, git = repo
    (path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    git("add", "app.py")
    assert main([]) == 0


def test_utf16_file_is_scanned_not_skipped(repo):
    # Review finding: PowerShell 5.1 `>` writes UTF-16; it used to pass as "OK" unscanned.
    path, git = repo
    (path / "notes.txt").write_bytes(f"key {FAKE['openrouter-key']}\n".encode("utf-16"))
    git("add", "notes.txt")
    assert main([]) == 1


def test_non_utf8_bytes_do_not_hide_a_secret(repo):
    path, git = repo
    content = "caf\xe9 ".encode("cp1252") + FAKE["aws-access-key"].encode() + b"\n"
    (path / "legacy.txt").write_bytes(content)
    git("add", "legacy.txt")
    assert main([]) == 1


def test_all_mode_scans_staged_files_before_first_commit(repo):
    path, git = repo
    (path / "app.py").write_text(f"K = '{FAKE['github-token']}'\n", encoding="utf-8")
    git("add", "app.py")
    assert main(["--all"]) == 1


@pytest.fixture
def hook_env(tmp_path, monkeypatch):
    """Simulate the pre-commit hook: git points GIT_INDEX_FILE at the commit being made."""
    outer_index = tmp_path / "outer-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(outer_index))
    return outer_index


def test_repo_fixture_is_isolated_from_hook_environment(hook_env, repo):
    # hook_env is set up BEFORE repo, exactly like running inside the hook.
    path, git = repo
    (path / "app.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "app.py")
    assert main([]) == 0
    assert not hook_env.exists()  # the "real" commit's index was never written
