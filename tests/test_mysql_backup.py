"""The SQLite backup CLI rejects MySQL before touching the destination."""

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from uuid import uuid4

from flask import Flask

from lifetime.cli import register_cli
from lifetime.database import make_engine
from lifetime.repositories.reference import ReferenceRepository


ROOT = Path(__file__).resolve().parents[1]


class BackupProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = (ROOT / ".artifacts" / ("backup-profile-" + uuid4().hex)).resolve()
        self.directory.mkdir(parents=True)
        self.engines = []
        self.app = Flask("backup_profile_test")
        self.app.config["APP_VERSION"] = "2.1.0"
        register_cli(self.app)
        self.destination = self.directory / "output"

    def tearDown(self):
        for engine in self.engines:
            engine.dispose()
        if self.directory.parent == (ROOT / ".artifacts").resolve() and self.directory.name.startswith(
            "backup-profile-"
        ):
            shutil.rmtree(self.directory)

    def sqlite(self, name):
        engine = make_engine(f"sqlite:///{self.directory / (name + '.sqlite3')}")
        self.engines.append(engine)
        return engine

    def invoke(self):
        return self.app.test_cli_runner().invoke(args=["backup", str(self.destination)])

    def test_mysql_rejected_without_connection_or_destination(self):
        mysql = SimpleNamespace(
            dialect=SimpleNamespace(name="mysql"), url=SimpleNamespace(database="lifetime")
        )
        self.app.extensions.update(reference_engine=mysql, analytics_engine=mysql)
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("docs/MYSQL.md", result.output)
        self.assertFalse(self.destination.exists())

    def test_mixed_profile_rejected_before_partial_sqlite_backup(self):
        mysql = SimpleNamespace(
            dialect=SimpleNamespace(name="mysql"), url=SimpleNamespace(database="analytics")
        )
        self.app.extensions.update(reference_engine=self.sqlite("reference"), analytics_engine=mysql)
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertFalse(self.destination.exists())

    def test_memory_profile_rejected_before_destination(self):
        engine = make_engine("sqlite:///:memory:")
        self.engines.append(engine)
        self.app.extensions.update(reference_engine=engine, analytics_engine=engine)
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("file-based SQLite", result.output)
        self.assertFalse(self.destination.exists())

    def test_sqlite_backup_keeps_committed_wal_data_and_metadata(self):
        reference, analytics = self.sqlite("reference"), self.sqlite("analytics")
        self.app.extensions.update(reference_engine=reference, analytics_engine=analytics)
        ReferenceRepository(reference).migrate()
        for engine in (reference, analytics):
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE backup_probe (value TEXT NOT NULL)")
                connection.exec_driver_sql("INSERT INTO backup_probe (value) VALUES (?)", ("committed",))
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        for name in ("reference", "analytics"):
            with closing(sqlite3.connect(self.destination / f"{name}.sqlite3")) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM backup_probe").fetchone()[0], "committed"
                )
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        metadata = json.loads((self.destination / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["app_version"], "2.1.0")
        self.assertIsNone(metadata["active_dataset"])


if __name__ == "__main__":
    unittest.main()
