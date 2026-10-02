"""Explicit environment configuration; no SQL or network at module import."""

import os
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def settings(overrides=None):
    directory = Path(os.environ.get("LIFETIME_DATA_DIR", str(ROOT / "instance"))).resolve()
    result = {
        "ENVIRONMENT": os.environ.get("ENVIRONMENT", "development"),
        "SERVICE_URL": os.environ.get("SERVICE_URL", "http://127.0.0.1:8000").rstrip("/"),
        "DATA_DIR": directory,
        "REFERENCE_DATABASE_URL": os.environ.get(
            "REFERENCE_DATABASE_URL", f"sqlite:///{directory / 'reference.sqlite3'}"
        ),
        "ANALYTICS_DATABASE_URL": os.environ.get(
            "ANALYTICS_DATABASE_URL", f"sqlite:///{directory / 'analytics.sqlite3'}"
        ),
        "ANALYTICS_SECRET": os.environ.get("ANALYTICS_SECRET", ""),
        "ANALYTICS_ENABLED": True,
        "ANALYTICS_STORE_RAW_IP": os.environ.get("ANALYTICS_STORE_RAW_IP", "false").lower() == "true",
        "ANALYTICS_RETENTION_DAYS": int(os.environ.get("ANALYTICS_RETENTION_DAYS", "90")),
        "ANALYTICS_RAW_IP_DAYS": int(os.environ.get("ANALYTICS_RAW_IP_DAYS", "7")),
        "ANALYTICS_AGGREGATE_DAYS": int(os.environ.get("ANALYTICS_AGGREGATE_DAYS", "365")),
        "TRUSTED_PROXY_CIDRS": tuple(filter(None, os.environ.get("TRUSTED_PROXY_CIDRS", "").split(","))),
        "MAX_CONTENT_LENGTH": 16384,
        "MAX_FORM_MEMORY_SIZE": 16384,
        "MAX_FORM_PARTS": 12,
        "TIMEZONE": ZoneInfo("Europe/Kyiv"),
        "SNAPSHOT_PATH": ROOT / "data" / "life_expectancy",
        "CONTENT_UPDATED": "2026-10-03",
        "TESTING": False,
    }
    if overrides:
        result.update(overrides)
    origin = urlsplit(result["SERVICE_URL"])
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("SERVICE_URL must be an absolute HTTP(S) origin without path or credentials")
    if result["ENVIRONMENT"] == "production":
        if origin.scheme != "https":
            raise ValueError("Production SERVICE_URL must use HTTPS")
        if len(result["ANALYTICS_SECRET"]) < 32:
            raise ValueError("Production requires ANALYTICS_SECRET with at least 32 characters")
    result.setdefault("TRUSTED_HOSTS", [origin.hostname, "localhost", "127.0.0.1", "[::1]"])

    def database_identity(value):
        url = make_url(value)
        if url.get_backend_name() == "sqlite" and url.database not in {None, "", ":memory:"}:
            return ("sqlite", os.path.normcase(str(Path(url.database).resolve())))
        return value

    if database_identity(result["REFERENCE_DATABASE_URL"]) == database_identity(
        result["ANALYTICS_DATABASE_URL"]
    ):
        raise ValueError("Reference and analytics databases must be separate")
    for key in ("ANALYTICS_RETENTION_DAYS", "ANALYTICS_RAW_IP_DAYS", "ANALYTICS_AGGREGATE_DAYS"):
        if result[key] < 0:
            raise ValueError(f"{key} must be nonnegative")
    return result
