"""Check tracked files for private artifacts and historical request-log seeds.

Reports paths and rule names only, never matching contents. Secret scanning is
provided separately by Gitleaks; this covers sensitive files and log data that
token/entropy scanners do not recognize.
"""

from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".cnf", ".log", ".jsonl"}
PRIVATE_DIRECTORIES = {".ssh", ".venv", "backups", "certificates", "instance", "state", ".artifacts"}
LOG_ROWS = re.compile(
    r"\b(?:INSERT(?:\s+IGNORE)?|REPLACE)\s+INTO\s+[`\"]?(?:log|request_events|request_daily)[`\"]?\s*(?:\(|VALUES\b)",
    re.I,
)
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def violations(name, content):
    path = PurePosixPath(name)
    if (
        path.suffix.lower() in PRIVATE_SUFFIXES
        or set(path.parts) & PRIVATE_DIRECTORIES
        or (path.name.startswith(".env") and path.name != ".env.example")
        or path.name in {"id_rsa", "id_ed25519", ".desktop-account-host"}
        or name == "app/config.py"
    ):
        yield "private artifact"
    if path.suffix.lower() == ".sql":
        text = content.decode("utf-8", errors="replace")
        if LOG_ROWS.search(text):
            yield "historical request rows"
        if IPV4.search(text):
            yield "IP address in SQL seed"


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    failures = []
    for name in filter(None, names):
        path = ROOT / name
        if path.is_file():
            failures.extend(f"{name}: {rule}" for rule in violations(name, path.read_bytes()))
    if failures:
        print("\n".join(failures))
        return 1
    print("Tracked-file privacy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
