"""Full Flask/CLI/telemetry acceptance on one isolated MySQL database."""

from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import socket
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url

from lifetime import create_app
from lifetime.analytics.schema import events
from lifetime.repositories.schema import dataset_versions, life_expectancy
from lifetime.version import get_version

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("TEST_MYSQL_URL"), "TEST_MYSQL_URL is not configured")
class MySQLApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["TEST_MYSQL_URL"])
        if url.get_backend_name() != "mysql":
            raise ValueError("TEST_MYSQL_URL must use MySQL")
        cls.database_name = "lifetime_app_test_" + uuid.uuid4().hex
        if not re.fullmatch(r"lifetime_app_test_[0-9a-f]{32}", cls.database_name):
            raise ValueError("Unsafe QA database name")
        cls.admin = create_engine(url, pool_pre_ping=True)
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE DATABASE `{cls.database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
            )
        cls.folder = ROOT / "tests" / ("mysql-app-test-" + uuid.uuid4().hex)
        cls.folder.mkdir()
        cls.url = url.set(database=cls.database_name)
        cls.config = {
            "TESTING": True,
            "DB_BACKEND": "mysql",
            "DATA_DIR": cls.folder,
            "REFERENCE_DATABASE_URL": cls.url,
            "ANALYTICS_DATABASE_URL": cls.url,
            "ANALYTICS_SECRET": "mysql-app-QA-secret-0123456789abcdef",
            "SERVICE_URL": "https://lifetime.example",
            "TODAY": lambda: date(2026, 10, 3),
        }
        with patch(
            "sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Factory must not connect to SQL")
        ):
            cls.app = create_app(cls.config)
        cls.client = cls.app.test_client()
        cls.runner = cls.app.test_cli_runner()
        for args in (("migrate",), ("import-data", "--path", str(ROOT / "data" / "life_expectancy"))):
            outcome = cls.runner.invoke(args=list(args))
            if outcome.exit_code:
                raise AssertionError((outcome.output, outcome.exception))

    @classmethod
    def tearDownClass(cls):
        for key in ("reference_engine", "analytics_engine"):
            cls.app.extensions[key].dispose()
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(f"DROP DATABASE `{cls.database_name}`")
        cls.admin.dispose()
        if cls.folder.resolve().parent != (ROOT / "tests").resolve() or not cls.folder.name.startswith(
            "mysql-app-test-"
        ):
            raise ValueError("Unsafe QA directory cleanup")
        shutil.rmtree(cls.folder)

    def event_rows(self):
        with self.app.extensions["analytics_engine"].connect() as connection:
            return [dict(row) for row in connection.execute(select(events)).mappings()]

    def test_shared_database_has_independent_migration_chains_and_verified_reference(self):
        with self.app.extensions["reference_engine"].connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT DATABASE()")), self.database_name)
            self.assertEqual(
                connection.scalar(text("SELECT version_num FROM alembic_reference_version")), "reference_0002"
            )
            self.assertEqual(
                connection.scalar(text("SELECT version_num FROM alembic_version")), "analytics_0003"
            )
            self.assertEqual(connection.scalar(select(func.count()).select_from(life_expectancy)), 885)
        self.assertEqual(len(self.app.extensions["reference"].list_locations("uk")), 225)
        self.assertEqual(
            self.app.extensions["reference"].get_location("WLD")["values"]["total"], 73.4818184164654
        )
        self.assertIn("request_events", inspect(self.app.extensions["reference_engine"]).get_table_names())
        self.assertEqual(self.app.config["APP_VERSION"], get_version())
        self.assertEqual(get_version(), "2.1.0")

    def test_repeat_cli_migrations_and_import_are_idempotent(self):
        outcome = self.runner.invoke(args=["migrate"])
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        outcome = self.runner.invoke(args=["import-data", "--path", str(ROOT / "data" / "life_expectancy")])
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        self.assertFalse(json.loads(outcome.output)["imported"])
        with self.app.extensions["reference_engine"].connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(dataset_versions)), 1)

    def test_http_forms_errors_and_legacy_capture_one_event_each(self):
        before = {row["event_id"] for row in self.event_rows()}
        requests = [
            ("GET", "/uk", None, 200),
            ("GET", "/en", None, 200),
            ("GET", "/readyz", None, 200),
            ("GET", "/en/ukraine", None, 200),
            ("POST", "/en/result", {"birth_date": "2000-02-29", "country": "UKR", "sex": "female"}, 200),
            ("POST", "/uk/result", {"birth_date": "2026-10-04", "country": "UKR", "sex": "total"}, 400),
            ("GET", "/eng/result?birth_date=2000-01-01&country=181&sex=1", None, 200),
            ("GET", "/ukr/world", None, 301),
            ("GET", "/en/england", None, 200),
            ("GET", "/rus/ukraine", None, 410),
            ("GET", "/en/unknown/nested", None, 404),
        ]
        for method, path, form, status in requests:
            with self.subTest(path=path):
                response = self.client.open(path, method=method, data=form, buffered=True)
                self.assertEqual(response.status_code, status)
                if "result" in path:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertIn("noindex", response.headers["X-Robots-Tag"])
                if path == "/en/england":
                    self.assertIn('name="robots" content="noindex, follow"', response.text)
                if path == "/en/unknown/nested":
                    self.assertIn('<html lang="en">', response.text)
                if path in {"/uk", "/en"}:
                    self.assertIn("2.1.0", response.text)
        captured = [row for row in self.event_rows() if row["event_id"] not in before]
        self.assertEqual(len(captured), len(requests))
        self.assertTrue(all(row["app_version"] == "2.1.0" for row in captured))
        self.assertEqual(sum(row["validity"] == "invalid" for row in captured), 3)
        serialized = json.dumps(captured)
        for private_value in ("2000-02-29", "2000-01-01", "2026-10-04", "birth_date"):
            self.assertNotIn(private_value, serialized)
        self.assertEqual(self.app.extensions["analytics"].dropped_events, 0)

    def test_sitemap_uses_configured_origin_and_excludes_results_or_unavailable(self):
        response = self.client.get("/sitemap.xml", buffered=True)
        self.assertEqual(response.status_code, 200)
        document = ET.fromstring(response.data)
        urls = [element.text for element in document.findall("{*}url/{*}loc")]
        self.assertEqual(len(urls), 458)
        self.assertTrue(all(url.startswith("https://lifetime.example/") for url in urls))
        self.assertFalse(any("/result" in url or "/england" in url for url in urls))
        self.assertIn("https://lifetime.example/en/ukraine", urls)
        self.assertIn("https://lifetime.example/uk/ukraine", urls)
        self.assertIn(
            "https://lifetime.example/sitemap.xml", self.client.get("/robots.txt", buffered=True).text
        )

    def test_unavailable_mysql_is_not_ready_and_http_remains_fail_open_with_spool(self):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", 1)) == 0:
                self.skipTest("Expected refused local QA port is in use")
        url = self.url.set(host="127.0.0.1", port=1)
        config = {
            **self.config,
            "DATA_DIR": self.folder / "outage",
            "REFERENCE_DATABASE_URL": url,
            "ANALYTICS_DATABASE_URL": url,
        }
        app = create_app(config)
        try:
            response = app.test_client().get("/readyz", buffered=True)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(app.extensions["analytics"].dropped_events, 0)
            self.assertEqual(app.extensions["analytics"].spooled_events, 1)
            files = list((self.folder / "outage" / "spool").glob("*.json"))
            self.assertEqual(len(files), 1)
            event = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(event["status"], 503)
            self.assertEqual(event["app_version"], "2.1.0")
        finally:
            for key in ("reference_engine", "analytics_engine"):
                app.extensions[key].dispose()
