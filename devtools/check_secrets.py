"""Small, offline secret scanner used by the pre-commit hook.

Usage:
    python -m devtools.check_secrets            # scan files staged for commit (default)
    python -m devtools.check_secrets --all      # scan every tracked file

Scans the content in the git index (what would actually be committed), not the working
copy. Unreadable files fail the scan instead of being skipped.
Exits 1 if anything is found. Findings show file:line and the rule, never the secret.
A line can be allowed explicitly by adding the marker `secret-scan: allow`.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

ALLOW_MARKER = "secret-scan: allow"

# Files that must never be committed, whatever they contain (compared case-insensitively:
# on Windows ".ENV" is the same file as ".env").
FORBIDDEN_NAMES = {".env", "settings.local.json", "id_rsa", "id_ed25519"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".env"}  # ".env" catches "prod.env"
ALLOWED_ENV_FILES = {".env.example"}

# (rule name, pattern). Patterns target real key formats, so placeholders don't match.
RULES = [
    ("openrouter-key", re.compile(r"sk-or-v1-[0-9a-f]{32,}")),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # A real-looking value assigned to our key variable (the .env.example placeholder is fine).
    (
        "openrouter-key-assignment",
        # KEY=..., KEY: ..., "KEY": "...", env["KEY"] = "..."
        re.compile(r"OPENROUTER_API_KEY['\"\]]{0,2}\s*[:=]\s*['\"]?(?!your-)[A-Za-z0-9_\-]{20,}"),
    ),
]


@dataclass
class Finding:
    path: str
    line: int  # 0 = the file itself is forbidden
    rule: str

    def __str__(self) -> str:
        where = self.path if self.line == 0 else f"{self.path}:{self.line}"
        return f"{where}: {self.rule}"


def check_filename(path: str) -> Finding | None:
    name = PurePosixPath(path).name.lower()
    if name in ALLOWED_ENV_FILES:
        return None
    env_variant = name.startswith(".env.")  # .env.local, .env.prod, ...
    if name in FORBIDDEN_NAMES or env_variant or PurePosixPath(name).suffix in FORBIDDEN_SUFFIXES:
        return Finding(path, 0, "forbidden-file")
    return None


def scan_text(path: str, text: str) -> list[Finding]:
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        findings += [Finding(path, number, name) for name, rx in RULES if rx.search(line)]
    return findings


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout


def _staged_files() -> list[str]:
    # T = type change (e.g. a symlink replaced by a real file); deletions are not scanned.
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z")
    return [f for f in out.split("\0") if f]


def decode(raw: bytes) -> str:
    """Bytes -> text without ever skipping a file.

    Windows PowerShell 5.1 writes UTF-16 with `>`; a strict UTF-8 decode would fail and the
    file would silently go unscanned. Undecodable bytes are replaced, so binary files are
    still searched for key-shaped ASCII.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if raw and raw.count(b"\0") > len(raw) // 4:  # UTF-16 without BOM (mostly NUL bytes)
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _read(path: str) -> str:
    """The file's content in the index (what would be committed). Raises on git errors."""
    # ":0:" = stage 0 explicitly, so a path like "1:foo" is not read as a merge stage.
    raw = subprocess.run(["git", "show", f":0:{path}"], capture_output=True, check=True).stdout
    return decode(raw)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Offline secret scanner")
    p.add_argument("--all", action="store_true", help="scan all tracked files (the index)")
    args = p.parse_args(argv)

    files = [f for f in _git("ls-files", "-z").split("\0") if f] if args.all else _staged_files()
    findings: list[Finding] = []
    scanned = 0
    for path in files:
        if finding := check_filename(path):
            findings.append(finding)
            continue
        try:
            text = _read(path)
        except subprocess.CalledProcessError as e:
            # Fail closed: a file we could not read is a file we did not check.
            print(f"Secret scan ERROR: could not read {path}: {e.stderr.decode(errors='replace')}")
            return 2
        findings += scan_text(path, text)
        scanned += 1

    if findings:
        print("Secret scan FAILED. Remove these before committing:")
        for finding in findings:
            print(f"  {finding}")
        print(f"(False positive? Add '{ALLOW_MARKER}' to that line and explain why.)")
        return 1
    print(f"Secret scan: OK ({scanned} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
