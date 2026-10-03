"""MySQL reference acceptance tests, using a unique disposable test database.

TEST_MYSQL_URL must point to a QA server with CREATE/DROP DATABASE privilege.
Its supplied schema is never mutated. Without it, server checks are skipped.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import unittest
import uuid

from sqlalchemy import create_engine, func, insert, inspect, select, text, update
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from lifetime.repositories.reference import ReferenceRepository
from lifetime.repositories.schema import active_reference, dataset_versions, life_expectancy

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "life_expectancy"


class MySQLReferenceDDLTests(unittest.TestCase):
    def test_numeric_type_uses_mysql_binary64_and_sqlite_affinity(self):
        self.assertEqual(str(life_expectancy.c.value_years.type.compile(dialect=mysql.dialect())), "DOUBLE")
        self.assertEqual(str(life_expectancy.c.value_years.type.compile(dialect=sqlite.dialect())), "FLOAT")

    def test_singleton_id_is_not_auto_increment(self):
        ddl = str(CreateTable(active_reference).compile(dialect=mysql.dialect()))
        self.assertNotIn("AUTO_INCREMENT", ddl)
        self.assertIn("CHECK (id = 1)", ddl)


@unittest.skipUnless(os.environ.get("TEST_MYSQL_URL"), "TEST_MYSQL_URL is not configured")
class MySQLReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["TEST_MYSQL_URL"])
        if url.get_backend_name() != "mysql":
            raise ValueError("TEST_MYSQL_URL must use MySQL")
        cls.database_name = "lifetime_reference_test_" + uuid.uuid4().hex
        if not re.fullmatch(r"lifetime_reference_test_[0-9a-f]{32}", cls.database_name):
            raise ValueError("Unsafe test database name")
        cls.admin = create_engine(url, pool_pre_ping=True)
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE DATABASE `{cls.database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
            )
        cls.engine = create_engine(url.set(database=cls.database_name), pool_pre_ping=True)
        cls.repository = ReferenceRepository(cls.engine)
        cls.repository.migrate()
        cls.original_id = cls.repository.import_snapshot(BUNDLE)["id"]
        cls.repository.activate_dataset(cls.original_id)
        cls.folder = ROOT / "tests" / ("mysql-reference-test-" + uuid.uuid4().hex)
        cls.folder.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(f"DROP DATABASE `{cls.database_name}`")
        cls.admin.dispose()
        if cls.folder.resolve().parent != (ROOT / "tests").resolve() or not cls.folder.name.startswith(
            "mysql-reference-test-"
        ):
            raise ValueError("Unsafe test directory cleanup")
        shutil.rmtree(cls.folder)

    def revised_bundle(self):
        target = self.folder / uuid.uuid4().hex
        shutil.copytree(BUNDLE, target)
        snapshot = json.loads((target / "snapshot.json").read_text(encoding="utf-8"))
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        retrieval = "2026-10-03T00:00:00+00:00"
        snapshot["retrieved_at"] = manifest["retrieved_at"] = retrieval
        for observation in snapshot["observations"]:
            observation["retrieved_at"] = retrieval
        (target / "snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest["derived_files_sha256"]["snapshot.json"] = hashlib.sha256(
            (target / "snapshot.json").read_bytes()
        ).hexdigest()
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        return target

    def test_migration_repeatable_with_innodb_utf8mb4_and_double(self):
        self.repository.migrate()
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT version_num FROM alembic_reference_version")), "reference_0002"
            )
            rows = connection.execute(
                text(
                    "SELECT ENGINE, TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=:database AND TABLE_NAME IN ('locations','life_expectancy','legacy_aliases','dataset_versions','active_reference')"
                ),
                {"database": self.database_name},
            ).all()
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(engine == "InnoDB" and collation == "utf8mb4_bin" for engine, collation in rows))
        column = next(
            column
            for column in inspect(self.engine).get_columns("life_expectancy")
            if column["name"] == "value_years"
        )
        self.assertIsInstance(column["type"], mysql.DOUBLE)

    def test_snapshot_round_trips_all_original_precision_and_missing_values(self):
        snapshot = json.loads((BUNDLE / "snapshot.json").read_text(encoding="utf-8"))
        expected = {
            (entry["entity_code"], entry["sex"]): entry["value_years"] for entry in snapshot["observations"]
        }
        with self.engine.connect() as connection:
            values = {
                (code, sex): value
                for code, sex, value in connection.execute(
                    select(
                        life_expectancy.c.location_code, life_expectancy.c.sex, life_expectancy.c.value_years
                    ).where(life_expectancy.c.dataset_id == self.original_id)
                )
            }
        self.assertEqual(values, expected)
        self.assertEqual(sum(value is None for value in values.values()), 93)
        self.assertEqual(values["WLD", "total"], 73.4818184164654)
        self.assertEqual(self.repository.get_location("UKR", "uk")["name"], "Україна")
        self.assertEqual(len(self.repository.list_locations("en")), 225)
        self.assertFalse(self.repository.legacy_location("england")["available"])

    def test_idempotent_import_and_unknown_activation_leave_active_unchanged(self):
        self.repository.activate_dataset(self.original_id)
        summary = self.repository.import_snapshot(BUNDLE)
        self.assertFalse(summary["imported"])
        self.assertEqual(summary["id"], self.original_id)
        with self.assertRaisesRegex(ValueError, "unknown_dataset"):
            self.repository.activate_dataset("missing")
        self.assertEqual(self.repository.active_dataset()["id"], self.original_id)

    def test_foreign_key_and_check_constraints_enforced(self):
        cases = [
            insert(active_reference).values(id=2, dataset_id=self.original_id),
            update(active_reference).where(active_reference.c.id == 1).values(dataset_id="missing"),
            insert(life_expectancy).values(
                dataset_id=self.original_id,
                location_code="UKR",
                year=2023,
                sex="total",
                indicator="SP.DYN.LE00.IN",
                value_years=150,
                status="available",
                missing_reason=None,
                metadata_json="{}",
            ),
            insert(life_expectancy).values(
                dataset_id=self.original_id,
                location_code="ZZZ",
                year=2023,
                sex="total",
                indicator="SP.DYN.LE00.IN",
                value_years=75,
                status="available",
                missing_reason=None,
                metadata_json="{}",
            ),
            insert(life_expectancy).values(
                dataset_id=self.original_id,
                location_code="UKR",
                year=2023,
                sex="total",
                indicator="SP.DYN.LE00.IN",
                value_years=None,
                status="missing",
                missing_reason=None,
                metadata_json="{}",
            ),
        ]
        expected_error_codes = (3819, 1452, 3819, 1452, 3819)
        for statement, expected_error in zip(cases, expected_error_codes, strict=True):
            with self.subTest(statement=str(statement)), self.assertRaises(DBAPIError) as failure:
                with self.engine.begin() as connection:
                    connection.execute(statement)
            self.assertEqual(failure.exception.orig.args[0], expected_error)

    def test_failed_insert_rolls_back_entire_revision_then_activation_can_roll_back(self):
        self.repository.activate_dataset(self.original_id)
        target = self.revised_bundle()
        with self.engine.begin() as connection:
            prior_count = connection.scalar(select(func.count()).select_from(dataset_versions))
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_reference_import BEFORE INSERT ON life_expectancy FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'QA rejected staged import'"
            )
        try:
            with self.assertRaises(DBAPIError):
                self.repository.import_snapshot(target)
        finally:
            with self.engine.begin() as connection:
                connection.exec_driver_sql("DROP TRIGGER reject_reference_import")
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(select(func.count()).select_from(dataset_versions)), prior_count
            )
        self.assertEqual(self.repository.active_dataset()["id"], self.original_id)
        revised = self.repository.import_snapshot(target)["id"]
        self.assertNotEqual(revised, self.original_id)
        self.assertEqual(self.repository.active_dataset()["id"], self.original_id)
        self.repository.activate_dataset(revised)
        self.assertEqual(self.repository.active_dataset()["id"], revised)
        self.repository.activate_dataset(self.original_id)
        self.assertEqual(self.repository.active_dataset()["id"], self.original_id)
        self.assertEqual(self.repository.get_location("WLD")["values"]["total"], 73.4818184164654)

    def test_numeric_overflow_remains_unknown_location(self):
        self.assertIsNone(self.repository.get_location("9" * 5000))
        self.assertIsNone(self.repository.legacy_location("12345678901234567890"))
