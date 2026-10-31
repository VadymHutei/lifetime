"""Privacy regression checks for the repository guard, without real private data."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "repository_safety", Path(__file__).resolve().parents[1] / "scripts" / "check_repository_safety.py"
)
SAFETY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAFETY)


def test_private_files_are_rejected_without_echoing_contents():
    for name in (
        ".env.production",
        "app/config.py",
        "backups/db.sql",
        "instance/analytics.key",
        "client.cnf",
    ):
        findings = list(SAFETY.violations(name, b"synthetic-private-value"))
        assert findings == ["private artifact"]
        assert all("synthetic-private-value" not in finding for finding in findings)
    assert not list(SAFETY.violations(".env.example", b"DB_PASSWORD="))


def test_historical_request_data_is_rejected_in_sql():
    for statement in (
        b"INSERT INTO `log` (`id`) VALUES (1);",
        b"INSERT INTO log VALUES (1);",
        b"REPLACE INTO request_events (event_id) VALUES ('example');",
        b"INSERT IGNORE INTO request_daily (count) VALUES (1);",
    ):
        assert "historical request rows" in list(SAFETY.violations("seed.sql", statement))
    assert "IP address in SQL seed" in list(SAFETY.violations("seed.sql", b"-- client 192.0.2.1"))
    assert not list(SAFETY.violations("seed.sql", b"INSERT INTO countries (id) VALUES (1);"))
