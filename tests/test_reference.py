import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from flask import Flask

from lifetime.cli import register_cli

from lifetime.repositories.reference import ReferenceRepository
from lifetime.repositories.schema import dataset_versions, life_expectancy
from lifetime.repositories.snapshot import verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "life_expectancy"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_manifest(path):
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    for name in manifest["derived_files_sha256"]:
        manifest["derived_files_sha256"][name] = hashlib.sha256((path / name).read_bytes()).hexdigest()
    write_json(path / "manifest.json", manifest)


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT / "tests" / f"reference-test-{uuid.uuid4().hex}"
        self.folder.mkdir()
        self.engine = create_engine(f"sqlite:///{(self.folder / 'reference.sqlite').as_posix()}")

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        self.repository = ReferenceRepository(self.engine)
        self.repository.migrate()

    def tearDown(self):
        self.engine.dispose()
        if self.folder.resolve().parent != (ROOT / "tests").resolve() or not self.folder.name.startswith(
            "reference-test-"
        ):
            raise ValueError("Unsafe test cleanup target")
        shutil.rmtree(self.folder)

    def activated(self):
        summary = self.repository.import_snapshot(BUNDLE)
        self.repository.activate_dataset(summary["dataset_id"])
        return summary["dataset_id"]

    def copied(self):
        target = self.folder / "bundle"
        shutil.copytree(BUNDLE, target)
        return target

    def test_migration_explicit_and_repeatable(self):
        fresh = create_engine(f"sqlite:///{(self.folder / 'fresh.sqlite').as_posix()}")
        ReferenceRepository(fresh)
        self.assertEqual(inspect(fresh).get_table_names(), [])
        fresh.dispose()
        self.repository.migrate()
        self.assertIn("alembic_reference_version", inspect(self.engine).get_table_names())
        self.assertIsNone(self.repository.active_dataset())

    def test_staged_idempotent_import_preserves_original_precision(self):
        first = self.repository.import_snapshot(BUNDLE)
        self.assertTrue(first["imported"])
        self.assertIsNone(self.repository.active_dataset())
        second = self.repository.import_snapshot(BUNDLE)
        self.assertFalse(second["imported"])
        self.assertEqual(first["id"], second["id"])
        self.repository.activate_dataset(first["id"])
        self.assertEqual(self.repository.get_location("UKR")["values"]["total"], 74.692)
        self.assertEqual(self.repository.get_location("WLD")["values"]["total"], 73.4818184164654)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(life_expectancy)), 885)

    def test_public_localization_and_independent_regional_identity(self):
        self.activated()
        english = self.repository.list_locations("en")
        ukrainian = self.repository.list_locations("uk")
        self.assertEqual(len(english), 225)
        self.assertEqual({entry["code"] for entry in english}, {entry["code"] for entry in ukrainian})
        self.assertTrue(
            all(
                entry["name"] and any("А" <= char <= "я" or char in "ІЇЄієї" for char in entry["name"])
                for entry in ukrainian
            )
        )
        self.assertTrue(all(entry["available"] for entry in english))
        self.assertEqual(len({entry["slug"] for entry in english}), 225)
        self.assertEqual(self.repository.get_location("UKR", "uk")["name"], "Україна")
        self.assertEqual(self.repository.get_location("CHI")["entity_type"], "area")
        self.assertIsNone(self.repository.get_location("HIC"))
        self.assertNotEqual(self.repository.get_location("SAS")["slug"], "south-asia")

    def test_legacy_unavailable_never_maps_to_neighbor(self):
        self.activated()
        self.assertEqual(self.repository.legacy_location(181)["code"], "WLD")
        self.assertEqual(self.repository.legacy_location("ukraine")["code"], "UKR")
        for identifier in (7, 182, 183, 184, 185, 186, 187, 188):
            with self.subTest(identifier=identifier):
                view = self.repository.legacy_location(identifier)
                self.assertFalse(view["available"])
                self.assertEqual(view["values"], {"total": None, "female": None, "male": None})
                self.assertEqual(view["code"], f"legacy-{identifier}")
        self.assertFalse(self.repository.get_location("england")["available"])
        self.assertFalse(self.repository.get_location("europe-and-central-asia")["available"])
        self.assertIsNone(self.repository.get_location("unknown-location"))
        self.assertIsNone(self.repository.legacy_location(999))

    def test_oversized_numeric_identifiers_return_no_match(self):
        self.activated()
        for identifier in ("12345678901234567890", "9" * 5000, "2147483648", "0", "-181", "１８１"):
            with self.subTest(identifier=identifier[:30]):
                self.assertIsNone(self.repository.get_location(identifier))
                self.assertIsNone(self.repository.legacy_location(identifier))
        self.assertEqual(self.repository.legacy_location("181")["code"], "WLD")

    def test_backup_manifest_reads_copied_revision_after_live_activation(self):
        import sqlite3

        old_id = self.activated()
        target = self.copied()
        snapshot = json.loads((target / "snapshot.json").read_text(encoding="utf-8"))
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        revised_time = "2026-10-02T22:19:03+00:00"
        snapshot["retrieved_at"] = manifest["retrieved_at"] = revised_time
        for observation in snapshot["observations"]:
            observation["retrieved_at"] = revised_time
        write_json(target / "snapshot.json", snapshot)
        write_json(target / "manifest.json", manifest)
        update_manifest(target)
        new_id = self.repository.import_snapshot(target)["id"]
        analytics = create_engine(f"sqlite:///{(self.folder / 'analytics.sqlite').as_posix()}")
        app = Flask(__name__)
        app.config["APP_VERSION"] = "2.0.0"
        app.extensions.update(
            reference_engine=self.engine, analytics_engine=analytics, reference=self.repository
        )
        register_cli(app)
        repository = self.repository
        original_connect = sqlite3.connect

        class ActivateAfterBackup(sqlite3.Connection):
            def backup(connection, copied, **kwargs):
                super().backup(copied, **kwargs)
                repository.activate_dataset(new_id)

        def concurrent_activation_connect(database, *args, **kwargs):
            if str(database) == self.engine.url.database:
                kwargs["factory"] = ActivateAfterBackup
            return original_connect(database, *args, **kwargs)

        try:
            with patch("lifetime.cli.sqlite3.connect", concurrent_activation_connect):
                outcome = app.test_cli_runner().invoke(args=["backup", str(self.folder / "backup")])
            self.assertEqual(outcome.exit_code, 0, outcome.output)
            metadata = json.loads((self.folder / "backup" / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["active_dataset"]["id"], old_id)
            self.assertEqual(self.repository.active_dataset()["id"], new_id)
        finally:
            analytics.dispose()

    def test_invalid_bundle_retains_active_revision(self):
        active = self.activated()
        target = self.copied()
        (target / "raw" / "countries.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            self.repository.import_snapshot(target)
        self.assertEqual(self.repository.active_dataset()["id"], active)
        with self.assertRaisesRegex(ValueError, "unknown_dataset"):
            self.repository.activate_dataset("missing")
        self.assertEqual(self.repository.active_dataset()["id"], active)

    def test_semantic_validation_does_not_trust_rehashed_derived_values(self):
        target = self.copied()
        snapshot = json.loads((target / "snapshot.json").read_text(encoding="utf-8"))
        snapshot["observations"][0]["value_years"] = 99
        write_json(target / "snapshot.json", snapshot)
        update_manifest(target)
        with self.assertRaisesRegex(ValueError, "differs from raw"):
            verify_snapshot(target)

    def test_legacy_source_checksum_and_mapping_coverage(self):
        target = self.copied()
        (target / "legacy_input.sql").write_text("invalid audit source", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            verify_snapshot(target)
        (target / "legacy_input.sql").unlink()
        aliases = json.loads((target / "legacy_aliases.json").read_text(encoding="utf-8"))
        write_json(target / "legacy_aliases.json", aliases[:-1])
        update_manifest(target)
        with self.assertRaisesRegex(ValueError, "mapping coverage"):
            verify_snapshot(target)

    def test_production_bundle_works_without_historical_sql(self):
        original_is_file = Path.is_file

        def production_is_file(path):
            return False if path.suffix == ".sql" else original_is_file(path)

        with patch.object(Path, "is_file", production_is_file):
            summary = self.repository.import_snapshot(BUNDLE)
        self.repository.activate_dataset(summary["id"])
        self.assertEqual(self.repository.legacy_location(181)["code"], "WLD")

    def test_unverified_mapping_rejected_even_when_rehashed(self):
        target = self.copied()
        aliases = json.loads((target / "legacy_aliases.json").read_text(encoding="utf-8"))
        aliases[-1]["target_code"] = "GBR"
        write_json(target / "legacy_aliases.json", aliases)
        update_manifest(target)
        with self.assertRaisesRegex(ValueError, "Unverified legacy"):
            verify_snapshot(target)

    def test_revisions_reactivation_and_atomic_insert_rollback(self):
        old_id = self.activated()
        target = self.copied()
        snapshot = json.loads((target / "snapshot.json").read_text(encoding="utf-8"))
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        revised_time = "2026-10-02T22:19:02+00:00"
        snapshot["retrieved_at"] = manifest["retrieved_at"] = revised_time
        for observation in snapshot["observations"]:
            observation["retrieved_at"] = revised_time
        write_json(target / "snapshot.json", snapshot)
        write_json(target / "manifest.json", manifest)
        update_manifest(target)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TRIGGER reject_import BEFORE INSERT ON life_expectancy BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"
                )
            )
        with self.assertRaises(IntegrityError):
            self.repository.import_snapshot(target)
        with self.engine.begin() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(dataset_versions)), 1)
            connection.execute(text("DROP TRIGGER reject_import"))
        revised = self.repository.import_snapshot(target)["id"]
        self.assertNotEqual(revised, old_id)
        self.assertEqual(self.repository.active_dataset()["id"], old_id)
        self.repository.activate_dataset(revised)
        self.assertEqual(self.repository.active_dataset()["id"], revised)
        self.repository.activate_dataset(old_id)
        self.assertEqual(self.repository.active_dataset()["id"], old_id)
        self.assertEqual(len(self.repository.list_datasets()), 2)
