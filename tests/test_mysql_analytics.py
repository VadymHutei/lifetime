"""Opt-in behavior tests against a dedicated disposable MySQL 8.4 database.

Set TEST_MYSQL_URL explicitly. Cleanup touches only analytics tables, and the
database name is guarded to prevent accidental production use.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import delete, event as sql_event, insert, select, text
from sqlalchemy.engine import make_url

from lifetime.analytics import AnalyticsStore
from lifetime.analytics.schema import daily, events
from lifetime.database import make_engine


@unittest.skipUnless(os.environ.get("TEST_MYSQL_URL"), "Set TEST_MYSQL_URL for isolated MySQL integration")
class MySQLAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["TEST_MYSQL_URL"])
        if url.get_backend_name() != "mysql" or url.database != "lifetime_test":
            raise ValueError("MySQL tests require the dedicated lifetime_test database")
        cls.engine = make_engine(os.environ["TEST_MYSQL_URL"])
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=root)
        cls.store = AnalyticsStore(
            cls.engine, Path(cls.temporary.name) / "spool", "mysql-test-key", app_version="2.1.0"
        )
        cls.store.migrate()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temporary.cleanup()

    def setUp(self):
        with self.engine.begin() as connection:
            connection.execute(delete(events))
            connection.execute(delete(daily))
        self.store.store_raw_ip = False
        self.store.dropped_events = 0
        self.store.spooled_events = 0
        for path in self.store.spool_dir.glob("*.json"):
            path.unlink()

    def event(self, **kwargs):
        return {
            "path": "/en",
            "method": "GET",
            "status": 200,
            "ip": "2001:db8::1",
            "validity": "valid",
            **kwargs,
        }

    def rows(self):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(events)).mappings()]

    def test_mysql_schema_migrations_and_large_response_counter(self):
        self.store.migrate()
        self.store.migrate()
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                "analytics_0003",
            )
            self.assertIn("ONLY_FULL_GROUP_BY", connection.execute(text("SELECT @@sql_mode")).scalar_one())
        self.assertEqual(self.store.record(self.event(response_bytes=2**40)), "inserted")
        self.assertEqual(self.rows()[0]["response_bytes"], 2**40)

    def test_fresh_tables_override_external_server_storage_defaults(self):
        name = "lifetime_test_analytics_options_" + uuid.uuid4().hex[:12]
        self.assertRegex(name, r"^lifetime_test_analytics_options_[a-f0-9]{12}$")
        url = make_url(os.environ["TEST_MYSQL_URL"])
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(
                text("CREATE DATABASE `" + name + "` CHARACTER SET latin1 COLLATE latin1_swedish_ci")
            )
        fresh_engine = None
        try:
            fresh_engine = make_engine(url.set(database=name))

            @sql_event.listens_for(fresh_engine, "connect")
            def legacy_engine_default(connection, _record):
                cursor = connection.cursor()
                cursor.execute("SET SESSION default_storage_engine='MyISAM'")
                cursor.close()

            fresh = AnalyticsStore(
                fresh_engine,
                Path(self.temporary.name) / "options-spool",
                "mysql-options-test-key",
                app_version="2.1.0",
            )
            fresh.migrate()
            with fresh_engine.connect() as connection:
                options = connection.execute(
                    text(
                        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=:schema AND TABLE_NAME IN ('request_events','daily_request_counts') ORDER BY TABLE_NAME"
                    ),
                    {"schema": name},
                ).all()
            self.assertEqual(
                options,
                [
                    ("daily_request_counts", "InnoDB", "utf8mb4_bin"),
                    ("request_events", "InnoDB", "utf8mb4_bin"),
                ],
            )
            self.assertEqual(fresh.record(self.event()), "inserted")
        finally:
            if fresh_engine is not None:
                fresh_engine.dispose()
            self.assertRegex(name, r"^lifetime_test_analytics_options_[a-f0-9]{12}$")
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
                admin.execute(text("DROP DATABASE `" + name + "`"))

    def test_privacy_and_independent_reports_use_native_json(self):
        self.store.record(
            self.event(
                user_agent="Googlebot DOB=1990-01-02",
                query_string="birth_date=1990-01-02&admin_key=SECRET&country=ukraine",
                referer="https://user:SECRET@example.org/?birth_date=1990-01-02",
            )
        )
        self.store.record(self.event(path="/.env", validity="invalid", status=404, user_agent="Firefox"))
        rows = self.rows()
        serialized = json.dumps(rows)
        for secret in ("1990-01-02", "SECRET", "birth_date", "admin_key", "2001:db8::1"):
            self.assertNotIn(secret, serialized)
        self.assertIsInstance(rows[0]["reasons"], list)
        self.assertIsInstance(rows[0]["query"], dict)
        self.assertEqual(self.store.report("valid")["total"], 1)
        self.assertEqual(self.store.report("bots")["total"], 1)
        self.assertEqual(self.store.report("invalid")["total"], 1)
        self.assertEqual(self.store.report("suspicious")["total"], 1)
        self.assertEqual(sum(item["count"] for item in self.store.report()["matrix"]), 2)

    def test_concurrent_writers_and_replay_have_no_loss(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: self.store.record(self.event()), range(120)))
        self.assertTrue(set(outcomes) <= {"inserted", "spooled"})
        result = self.store.replay()
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(self.rows()), 120)
        self.assertEqual(len({row["event_id"] for row in self.rows()}), 120)

    def test_concurrent_edge_annotations_preserve_app_and_final_outcome(self):
        edge_id = uuid.uuid4().hex
        app = self.event(
            edge_request_id=edge_id, endpoint="web.home", dataset_id="wdi-2024", user_agent="Googlebot"
        )
        edge = self.event(
            edge_request_id=edge_id, source="edge", status=502, validity="unknown", response_bytes=3
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.store.record, [edge, app] * 20))
        self.assertEqual(self.store.replay()["failed"], 0)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "app")
        self.assertEqual(rows[0]["endpoint"], "web.home")
        self.assertEqual(rows[0]["dataset_id"], "wdi-2024")
        self.assertEqual(rows[0]["client_class"], "claimed_bot")
        self.assertEqual(rows[0]["validity"], "valid")
        self.assertEqual(rows[0]["status"], 502)
        self.assertNotIn("edge_only", rows[0]["flags"])

    def test_actual_row_lock_spools_with_bounded_wait_then_deduplicates(self):
        edge_id = uuid.uuid4().hex
        self.store.record(self.event(edge_request_id=edge_id))
        with self.engine.begin() as locked:
            locked.execute(select(events).where(events.c.edge_request_id == edge_id).with_for_update()).all()
            started = time.perf_counter()
            result = self.store.record(self.event(edge_request_id=edge_id, source="edge", status=502))
            elapsed = time.perf_counter() - started
            self.assertEqual(result, "spooled")
            self.assertLess(elapsed, 4)
        self.assertEqual(self.store.replay()["merged"], 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["status"], 502)

    def test_database_outage_durably_replays_without_duplicates(self):
        with patch.object(self.store, "_insert", side_effect=OSError):
            self.assertEqual(self.store.record(self.event()), "spooled")
        original = next(self.store.spool_dir.glob("*.json")).read_text()
        self.assertEqual(self.store.replay()["inserted"], 1)
        self.store.spool_dir.joinpath("retry.json").write_text(original)
        self.assertEqual(self.store.replay()["duplicate"], 1)
        self.assertEqual(len(self.rows()), 1)

    def test_purge_batches_atomic_rollup_and_raw_ip_retention(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=100)).isoformat()
        safe = [self.store._safe(self.event(timestamp=old)) for _ in range(1050)]
        with self.engine.begin() as connection:
            connection.execute(insert(events), safe)
        self.store.store_raw_ip = True
        self.store.record(self.event(timestamp=(now - timedelta(days=10)).isoformat()))
        result = self.store.purge(now)
        self.assertNotIn("database_failed", result)
        self.assertEqual(result["events"], 1050)
        self.assertEqual(result["raw_ips"], 1)
        self.assertEqual(sum(row["count"] for row in self.store.report("daily")["rows"]), 1050)
        self.store.purge(now)
        self.assertEqual(sum(row["count"] for row in self.store.report("daily")["rows"]), 1050)
        self.assertIsNone(self.rows()[0]["raw_ip"])

    def test_purge_does_not_delete_unselected_backdated_replay(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=100)).isoformat()
        self.store.record(self.event(timestamp=old))
        late = self.store._safe(self.event(timestamp=old))
        inserted = []

        def replay_between_select_and_delete(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ):
            if statement.startswith("DELETE FROM request_events") and not inserted:
                inserted.append(True)
                with self.engine.begin() as writer:
                    writer.execute(insert(events).values(**late))

        sql_event.listen(self.engine, "before_cursor_execute", replay_between_select_and_delete)
        try:
            result = self.store.purge(now)
        finally:
            sql_event.remove(self.engine, "before_cursor_execute", replay_between_select_and_delete)
        self.assertNotIn("database_failed", result)
        self.assertEqual(result["events"], 2)
        self.assertEqual(sum(row["count"] for row in self.store.report("daily")["rows"]), 2)
        self.assertEqual(self.rows(), [])

    def test_parallel_purgers_preserve_counts_and_bigint_aggregate(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=100)).isoformat()
        safe = [self.store._safe(self.event(timestamp=old)) for _ in range(1250)]
        with self.engine.begin() as connection:
            connection.execute(insert(events), safe)
            connection.execute(
                insert(daily).values(
                    day=safe[0]["timestamp"][:10],
                    validity="valid",
                    client_class="unknown",
                    security_class="normal",
                    outcome="success",
                    count=2**40,
                )
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.purge(now), range(2)))
        self.assertTrue(all("database_failed" not in result for result in results))
        # Successful batches remain atomic and never count the same row twice.
        final = self.store.purge(now)
        self.assertNotIn("database_failed", final)
        self.assertEqual(sum(row["count"] for row in self.store.report("daily")["rows"]), 2**40 + 1250)
        self.assertEqual(sum(result["events"] for result in results) + final["events"], 1250)
        self.assertEqual(self.rows(), [])

    def test_edge_only_jsonl_idempotently_ingests_413_and_502(self):
        path = Path(self.temporary.name) / "edge.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(
                    self.event(
                        edge_request_id=uuid.uuid4().hex, source="edge", validity="unknown", status=status
                    )
                )
                for status in (413, 502)
            )
        )
        self.assertEqual(self.store.ingest_edge(path)["inserted"], 2)
        self.store.ingest_edge(path)
        self.assertEqual(len(self.rows()), 2)
        self.assertTrue(all("edge_only" in row["flags"] for row in self.rows()))
