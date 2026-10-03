"""Explicit environment configuration; no SQL or network at module import."""

import os
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]


def settings(overrides=None):
    directory = Path(os.environ.get("LIFETIME_DATA_DIR", str(ROOT / "instance"))).resolve()
    result = {
        "ENVIRONMENT": os.environ.get("ENVIRONMENT", "development"),
        "SERVICE_URL": os.environ.get("SERVICE_URL", "http://127.0.0.1:8000").rstrip("/"),
        "DATA_DIR": directory,
        "DB_BACKEND": os.environ.get("DB_BACKEND", "mysql").lower(),
        "DB_HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "DB_PORT": int(os.environ.get("DB_PORT", "3306")),
        "DB_NAME": os.environ.get("DB_NAME", "lifetime"),
        "DB_USER": os.environ.get("DB_USER", "lifetime"),
        "DB_PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "DB_SSL_CA": os.environ.get("DB_SSL_CA", ""),
        "REFERENCE_DATABASE_URL": os.environ.get("REFERENCE_DATABASE_URL") or None,
        "ANALYTICS_DATABASE_URL": os.environ.get("ANALYTICS_DATABASE_URL") or None,
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
    if result["DB_BACKEND"] not in {"mysql", "sqlite"}:
        raise ValueError("DB_BACKEND must be mysql or sqlite")
    if not 1 <= result["DB_PORT"] <= 65535:
        raise ValueError("DB_PORT must be between 1 and 65535")
    for name in ("reference", "analytics"):
        key = name.upper() + "_DATABASE_URL"
        if not result[key]:
            if result["DB_BACKEND"] == "sqlite":
                result[key] = URL.create("sqlite", database=str(Path(result["DATA_DIR"]) / f"{name}.sqlite3"))
            else:
                # URL.create accepts passwords literally, including @, :, /, %, and #.
                result[key] = URL.create(
                    "mysql+pymysql",
                    username=result["DB_USER"],
                    password=result["DB_PASSWORD"],
                    host=result["DB_HOST"],
                    port=result["DB_PORT"],
                    database=result["DB_NAME"],
                    query={"charset": "utf8mb4"},
                )
        url = make_url(result[key])
        if url.drivername not in {"mysql+pymysql", "sqlite", "sqlite+pysqlite"}:
            raise ValueError("Database URLs must use mysql+pymysql or sqlite")
        if url.get_backend_name() == "mysql" and (not url.host or not url.database or not url.username):
            raise ValueError("MySQL requires DB_HOST, DB_NAME and DB_USER (or complete database URLs)")
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
        for key in ("REFERENCE_DATABASE_URL", "ANALYTICS_DATABASE_URL"):
            url = make_url(result[key])
            if url.get_backend_name() == "mysql" and not url.password:
                raise ValueError("Production MySQL requires DB_PASSWORD (or a password in database URLs)")
    result.setdefault("TRUSTED_HOSTS", [origin.hostname, "localhost", "127.0.0.1", "[::1]"])

    def database_identity(value):
        url = make_url(value)
        if url.get_backend_name() == "sqlite" and url.database not in {None, "", ":memory:"}:
            return ("sqlite", os.path.normcase(str(Path(url.database).resolve())))
        return value

    if make_url(result["REFERENCE_DATABASE_URL"]).get_backend_name() == "sqlite" and database_identity(
        result["REFERENCE_DATABASE_URL"]
    ) == database_identity(result["ANALYTICS_DATABASE_URL"]):
        raise ValueError("Reference and analytics databases must be separate")
    for key in ("ANALYTICS_RETENTION_DAYS", "ANALYTICS_RAW_IP_DAYS", "ANALYTICS_AGGREGATE_DAYS"):
        if result[key] < 0:
            raise ValueError(f"{key} must be nonnegative")
    return result
