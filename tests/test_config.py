"""Configuration boundaries and factory behavior without production databases."""

import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import inspect

from lifetime import create_app
from lifetime.config import settings


ROOT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT / "tests" / f"config-test-{uuid.uuid4().hex}"
        self.folder.mkdir()
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            for key in ("reference_engine", "analytics_engine"):
                app.extensions[key].dispose()
        self.environment.stop()
        if self.folder.resolve().parent != (ROOT / "tests").resolve() or not self.folder.name.startswith(
            "config-test-"
        ):
            raise ValueError("Unsafe test cleanup target")
        shutil.rmtree(self.folder)

    def application(self, **overrides):
        config = {
            "DATA_DIR": self.folder,
            "ANALYTICS_ENABLED": False,
            "REFERENCE_DATABASE_URL": f"sqlite:///{(self.folder / 'reference.sqlite').as_posix()}",
            "ANALYTICS_DATABASE_URL": f"sqlite:///{(self.folder / 'analytics.sqlite').as_posix()}",
            "ANALYTICS_SECRET": "config-test-explicit-key-0123456789",
        }
        config.update(overrides)
        app = create_app(config)
        self.apps.append(app)
        return app

    def test_production_requires_https_and_explicit_secret(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            settings(
                {
                    "ENVIRONMENT": "production",
                    "SERVICE_URL": "http://lifetime.example",
                    "ANALYTICS_SECRET": "x" * 32,
                }
            )
        for secret in ("", "x" * 31):
            with (
                self.subTest(secret_length=len(secret)),
                self.assertRaisesRegex(ValueError, "ANALYTICS_SECRET"),
            ):
                settings(
                    {
                        "ENVIRONMENT": "production",
                        "SERVICE_URL": "https://lifetime.example",
                        "ANALYTICS_SECRET": secret,
                    }
                )
        config = settings(
            {
                "ENVIRONMENT": "production",
                "SERVICE_URL": "https://lifetime.example",
                "ANALYTICS_SECRET": "x" * 32,
            }
        )
        self.assertEqual(config["SERVICE_URL"], "https://lifetime.example")

    def test_canonical_origin_rejects_credentials_and_path(self):
        for origin in (
            "lifetime.example",
            "ftp://lifetime.example",
            "https://name:password@lifetime.example",
            "https://lifetime.example/path",
            "https://lifetime.example?token=x",
            "https://lifetime.example#fragment",
        ):
            with self.subTest(origin=origin), self.assertRaisesRegex(ValueError, "SERVICE_URL"):
                settings({"SERVICE_URL": origin})

    def test_databases_are_distinct_even_with_equivalent_file_paths(self):
        reference = f"sqlite:///{(self.folder / 'same.sqlite').as_posix()}"
        aliases = (
            reference,
            f"sqlite:///{self.folder.as_posix()}/./same.sqlite",
            f"sqlite:///{self.folder.as_posix()}/child/../same.sqlite",
        )
        for analytics in aliases:
            with self.subTest(analytics=analytics), self.assertRaisesRegex(ValueError, "separate"):
                settings({"REFERENCE_DATABASE_URL": reference, "ANALYTICS_DATABASE_URL": analytics})

    def test_negative_retention_is_rejected(self):
        for name in ("ANALYTICS_RETENTION_DAYS", "ANALYTICS_RAW_IP_DAYS", "ANALYTICS_AGGREGATE_DAYS"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "nonnegative"):
                settings({name: -1})

    def test_factory_does_not_migrate_or_import(self):
        app = self.application()
        self.assertFalse((self.folder / "reference.sqlite").exists())
        self.assertFalse((self.folder / "analytics.sqlite").exists())
        response = app.test_client().get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(inspect(app.extensions["reference_engine"]).get_table_names(), [])
        self.assertEqual(inspect(app.extensions["analytics_engine"]).get_table_names(), [])

    def test_unmatched_english_routes_preserve_error_language(self):
        app = self.application()
        for path in ("/en/unknown/nested", "/eng/unknown/nested"):
            response = app.test_client().get(path)
            with self.subTest(path=path):
                self.assertEqual(response.status_code, 404)
                self.assertIn('<html lang="en">', response.text)
                self.assertIn("noindex", response.headers["X-Robots-Tag"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_concurrent_factories_share_fully_published_local_key(self):
        config = {
            "DATA_DIR": self.folder,
            "ANALYTICS_ENABLED": False,
            "REFERENCE_DATABASE_URL": f"sqlite:///{(self.folder / 'reference.sqlite').as_posix()}",
            "ANALYTICS_DATABASE_URL": f"sqlite:///{(self.folder / 'analytics.sqlite').as_posix()}",
            "ANALYTICS_SECRET": "",
        }
        with ThreadPoolExecutor(max_workers=8) as workers:
            apps = list(workers.map(lambda _: create_app(config), range(16)))
        self.apps.extend(apps)
        keys = {app.extensions["analytics"].secret for app in apps}
        self.assertEqual(len(keys), 1)
        self.assertEqual(len(keys.pop()), 64)
        self.assertEqual(len((self.folder / "analytics.key").read_text(encoding="ascii")), 64)

    def test_trailing_slash_canonical_origin_is_normalized(self):
        with patch.dict(os.environ, {"SERVICE_URL": "https://lifetime.example/"}):
            self.assertEqual(settings()["SERVICE_URL"], "https://lifetime.example")
