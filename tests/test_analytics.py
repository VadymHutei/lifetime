"""Behavioral checks of capture, privacy, durable recovery and retention."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event as sql_event, select, text
from alembic import command
from alembic.config import Config
from werkzeug.test import Client
from werkzeug.wrappers import Response

from lifetime.analytics import AnalyticsStore, RequestAnalyticsMiddleware, sanitize_event
from lifetime.analytics.schema import events


def independent_worker(arguments):
    database, spool = arguments
    engine = create_engine("sqlite:///" + database, connect_args={"timeout": 0.05})
    store = AnalyticsStore(engine, spool, "worker-key", app_version="2.0.0")
    outcomes = [store.record({"path": "/uk", "method": "GET", "status": 200}) for _ in range(20)]
    engine.dispose()
    return outcomes


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=test_root)
        self.directory = Path(self.temporary.name)
        self.db = self.directory / "analytics.sqlite3"
        self.engine = create_engine("sqlite:///" + self.db.as_posix(), connect_args={"timeout": 0.05})

        @sql_event.listens_for(self.engine, "connect")
        def configure(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA busy_timeout=50")
            cursor.close()

        self.store = AnalyticsStore(self.engine, self.directory / "spool", "test-secret", app_version="2.0.0")
        self.store.migrate()

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def event(self, **kwargs):
        return {
            "path": "/uk",
            "method": "GET",
            "status": 200,
            "ip": "2001:db8::1",
            "user_agent": "Mozilla Firefox",
            **kwargs,
        }

    def rows(self):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(events)).mappings()]

    def test_explicit_migration_is_idempotent_and_views_exist(self):
        self.store.migrate()
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                "analytics_0002",
            )
            for name in ("valid_requests", "bot_requests", "invalid_requests", "suspicious_requests"):
                self.assertEqual(connection.execute(text("SELECT count(*) FROM " + name)).scalar_one(), 0)

    def test_key_id_migration_preserves_existing_events(self):
        for preexisting in (False, True):
            engine = create_engine("sqlite:///" + (self.directory / f"old-{preexisting}.sqlite3").as_posix())
            config = Config()
            config.set_main_option(
                "script_location", str(Path(__file__).resolve().parents[1] / "migrations" / "analytics")
            )
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "analytics_0001")
                original = sanitize_event(self.event(), "test-secret", "2.0.0")
                original.pop("address_key_id")
                connection.execute(events.insert().values(**original))
                if preexisting:
                    connection.execute(
                        text("ALTER TABLE request_events ADD COLUMN address_key_id VARCHAR(12)")
                    )
            upgraded = AnalyticsStore(
                engine, self.directory / "old-spool", "test-secret", app_version="2.0.0"
            )
            upgraded.migrate()
            upgraded.migrate()
            self.assertEqual(upgraded.report()["total"], 1)
            with engine.connect() as connection:
                row = connection.execute(select(events)).mappings().one()
                self.assertEqual(row["event_id"], original["event_id"])
                self.assertIsNone(row["address_key_id"])
            engine.dispose()

    def test_redaction_precedes_database_and_disk_with_ipv6(self):
        sensitive = self.event(
            path="/uk/result/1990-01-02/password=hunter2",
            query_string="birth_date=1990-01-02&admin_key=hunter2&country=123",
            user_agent="Firefox\r\nAuthorization: Bearer hunter2 a@example.com",
            referer="https://user:password@example.org/private?birth_date=1990-01-02",
            body="sensitive-body",
            authorization="hunter2",
        )
        with patch.object(self.store, "_insert", side_effect=RuntimeError):
            self.assertEqual(self.store.record(sensitive), "spooled")
        serialized = next((self.directory / "spool").glob("*.json")).read_text()
        for secret in (
            "1990-01-02",
            "hunter2",
            "a@example.com",
            "sensitive-body",
            "birth_date",
            "admin_key",
            "password",
        ):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("2001:db8::1", serialized)
        self.assertIn("https://example.org", serialized)
        self.assertEqual(self.store.replay()["inserted"], 1)
        row = self.rows()[0]
        self.assertEqual(row["address_family"], 6)
        self.assertEqual(row["path"], "/[redacted]")
        self.assertEqual(row["query"], {"country": "[redacted]"})
        self.assertEqual(len(row["address_token"]), 64)

    def test_valid_bot_human_404_and_probe_are_independent(self):
        self.store.record(self.event(user_agent="Googlebot", validity="valid"))
        self.store.record(self.event(status=404, path="/missing"))
        self.store.record(self.event(status=404, path="/.env"))
        self.store.record(self.event(status=500, validity="valid"))
        self.assertEqual(self.store.report("valid")["total"], 2)
        self.assertEqual(self.store.report("bots")["total"], 1)
        self.assertEqual(self.store.report("invalid")["total"], 2)
        self.assertEqual(self.store.report("suspicious")["total"], 1)
        overview = self.store.report()
        self.assertEqual(overview["total"], sum(row["count"] for row in overview["matrix"]))
        self.assertEqual(self.rows()[1]["client_class"], "unknown")
        self.assertEqual(self.rows()[3]["outcome"], "server_error")
        self.assertEqual(self.rows()[3]["validity"], "valid")

    def test_caller_cannot_assert_bot_verification(self):
        result = sanitize_event(
            self.event(client_class="verified_bot", user_agent="Googlebot", verified_bot_proof=True),
            "key",
            "2.0.0",
        )
        self.assertEqual(result["client_class"], "claimed_bot")

    def test_unknown_slugs_are_private_known_locations_are_recorded(self):
        unknown = sanitize_event(self.event(path="/uk/private-secret"), "key", "2.0.0")
        known = sanitize_event(self.event(path="/uk/ukraine", safe_path="/uk/ukraine"), "key", "2.0.0")
        self.assertEqual(unknown["path"], "/[redacted]")
        self.assertEqual(known["path"], "/uk/ukraine")
        self.assertEqual(sanitize_event(known, "key", "2.0.0")["path"], "/uk/ukraine")

    def test_unknown_static_filename_is_not_a_secret_storage_channel(self):
        safe = sanitize_event(self.event(path="/static/my-private-credential.js"), "key", "2.0.0")
        self.assertEqual(safe["path"], "/[redacted]")
        known = sanitize_event(self.event(path="/static/style.css"), "key", "2.0.0")
        self.assertEqual(known["path"], "/static/style.css")

    def test_spool_preserves_address_key_identifier_on_key_rotation(self):
        original = sanitize_event(self.event(), "old-secret", "2.0.0")
        replayed = sanitize_event(original, "new-secret", "2.0.0")
        self.assertEqual(replayed["address_token"], original["address_token"])
        self.assertEqual(replayed["address_key_id"], original["address_key_id"])

    def test_suspicious_reason_survives_spool_replay(self):
        with patch.object(self.store, "_insert", side_effect=RuntimeError):
            self.store.record(self.event(path="/private/../../etc/passwd", status=404))
        self.store.replay()
        row = self.rows()[0]
        self.assertEqual(row["security_class"], "suspicious")
        self.assertIn("probe_path", row["reasons"])

    def test_concurrent_writers_produce_one_event_each(self):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: self.store.record(self.event()), range(80)))
        self.assertTrue(set(outcomes) <= {"inserted", "spooled"})
        self.store.replay()
        self.assertEqual(len(self.rows()), 80)
        self.assertEqual(len({row["event_id"] for row in self.rows()}), 80)
        self.assertLess(time.perf_counter() - started, 5)

    def test_database_lock_durably_spools_then_replays_once(self):
        locked = sqlite3.connect(self.db)
        locked.execute("BEGIN IMMEDIATE")
        try:
            started = time.perf_counter()
            self.assertEqual(self.store.record(self.event()), "spooled")
            self.assertLess(time.perf_counter() - started, 0.5)
        finally:
            locked.rollback()
            locked.close()
        payload = next((self.directory / "spool").glob("*.json")).read_text()
        self.assertEqual(self.store.replay()["inserted"], 1)
        self.store.spool_dir.joinpath("retry.json").write_text(payload)
        self.assertEqual(self.store.replay()["duplicate"], 1)
        self.assertEqual(len(self.rows()), 1)

    def test_independent_worker_processes_share_database_and_atomic_spool(self):
        arguments = (self.db.as_posix(), self.store.spool_dir.as_posix())
        with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
            batches = list(pool.map(independent_worker, (arguments, arguments)))
        self.assertTrue({status for batch in batches for status in batch} <= {"inserted", "spooled"})
        self.store.replay()
        self.assertEqual(len(self.rows()), 40)

    def test_spool_and_database_failure_signal_drop_fail_open(self):
        bad_spool = self.directory / "file-not-directory"
        bad_spool.write_text("file")
        self.store.spool_dir = bad_spool
        with (
            patch.object(self.store, "_insert", side_effect=RuntimeError),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(self.store.record(self.event()), "dropped")
            self.assertIn("dropped_event", stderr.getvalue())
        self.assertEqual(self.store.dropped_events, 1)

    def test_replay_recovers_claim_and_signals_partial_write(self):
        self.store.spool_dir.mkdir()
        safe = sanitize_event(self.event(), "test-secret", "2.0.0")
        claimed = self.store.spool_dir / "crash.claim"
        claimed.write_text(json.dumps(safe))
        partial = self.store.spool_dir / "crash.tmp"
        partial.write_text('{"broken":')
        old = time.time() - 600
        os.utime(claimed, (old, old))
        os.utime(partial, (old, old))
        summary = self.store.replay()
        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["corrupt"], 1)
        self.assertEqual(self.store.dropped_events, 1)

    def test_edge_app_deduplicate_both_arrival_orders(self):
        for reverse in (False, True):
            edge_id = ("a" if reverse else "b") * 32
            edge = self.event(
                edge_request_id=edge_id, source="edge", status=502, response_bytes=100, duration_ms=25
            )
            app = self.event(
                edge_request_id=edge_id,
                status=200,
                validity="valid",
                endpoint="pages.home",
                dataset_id="wdi-2024",
            )
            first, second = (app, edge) if reverse else (edge, app)
            self.store.record(first)
            self.store.record(second)
            self.store.record(edge)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["source"], "app")
            self.assertEqual(row["status"], 502)
            self.assertEqual(row["validity"], "valid")
            self.assertEqual(row["dataset_id"], "wdi-2024")
            self.assertNotIn("edge_only", row["flags"])

    def test_edge_ingestion_413_and_502_without_app(self):
        path = self.directory / "edge.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(
                    self.event(edge_request_id=str(status)[0] * 32, status=status, duration_seconds=0.2)
                )
                for status in (413, 502)
            )
            + "\nnot-json\n"
        )
        result = self.store.ingest_edge(path)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(result["invalid_lines"], 1)
        self.assertEqual(len(self.rows()), 2)
        self.store.ingest_edge(path)
        self.assertEqual(len(self.rows()), 2)
        for row in self.rows():
            self.assertIn("edge_only", row["flags"])
            self.assertEqual(row["duration_ms"], 200)

    def test_retention_rolls_up_once_and_removes_raw_ip(self):
        self.store.store_raw_ip = True
        now = datetime.now(timezone.utc)
        self.store.record(self.event(timestamp=(now - timedelta(days=100)).isoformat()))
        self.store.record(self.event(timestamp=(now - timedelta(days=10)).isoformat()))
        self.store.record(self.event(timestamp=now.isoformat()))
        result = self.store.purge(now)
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["raw_ips"], 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertIsNone(self.rows()[0]["raw_ip"])
        self.assertEqual(self.rows()[1]["raw_ip"], "2001:db8::1")
        self.assertEqual(sum(row["count"] for row in self.store.report("daily")["rows"]), 1)
        self.store.purge(now)
        self.assertEqual(sum(row["count"] for row in self.store.report("daily")["rows"]), 1)
        self.store.purge(now + timedelta(days=400))
        self.assertEqual(self.store.report("daily")["rows"], [])

    def test_spool_retention_and_raw_ip_expiry(self):
        self.store.store_raw_ip = True
        now = datetime.now(timezone.utc)
        with patch.object(self.store, "_insert", side_effect=RuntimeError):
            self.store.record(self.event(timestamp=(now - timedelta(days=100)).isoformat()))
            self.store.record(self.event(timestamp=(now - timedelta(days=10)).isoformat()))
        result = self.store.purge(now)
        self.assertEqual(result["spool_events"], 1)
        self.assertEqual(result["spool_raw_ips"], 1)
        payloads = list(self.store.spool_dir.glob("*.json"))
        self.assertEqual(len(payloads), 1)
        self.assertIsNone(json.loads(payloads[0].read_text())["raw_ip"])

    def test_database_outage_does_not_prevent_spool_retention(self):
        now = datetime.now(timezone.utc)
        with patch.object(self.store, "_insert", side_effect=RuntimeError):
            self.store.record(self.event(timestamp=(now - timedelta(days=100)).isoformat()))
        with patch.object(self.engine, "begin", side_effect=RuntimeError):
            result = self.store.purge(now)
        self.assertEqual(result["database_failed"], 1)
        self.assertEqual(result["spool_events"], 1)
        self.assertEqual(list(self.store.spool_dir.glob("*.json")), [])

    def test_zero_retention_disables_detailed_capture(self):
        self.store.retain_days = 0
        self.assertEqual(self.store.record(self.event()), "disabled")
        self.assertEqual(self.rows(), [])

    def test_report_uses_allowlist_and_exclusive_matrix(self):
        self.store.record(self.event())
        with self.assertRaises(ValueError):
            self.store.report("valid; DROP TABLE request_events")
        self.assertEqual(self.store.report("normal")["total"], 1)
        self.assertEqual(self.store.report(since="2000-01-01")["total"], 1)

    def make_client(self, proxy=()):
        def app(environ, start_response):
            path = environ["PATH_INFO"]
            status = int(path.strip("/") or "200")
            if status == 500:
                environ["lifetime.validity"] = "valid"
            start_response(str(status) + " response", [("Content-Type", "text/plain")])
            return [] if environ["REQUEST_METHOD"] == "HEAD" or status == 304 else [b"ok"]

        return Client(RequestAnalyticsMiddleware(app, self.store, proxy, app_version="2.0.0"), Response)

    def test_capture_status_head_redirect_and_errors_once(self):
        client = self.make_client()
        for status in (200, 304, 301, 400, 404, 405, 500):
            response = client.get("/" + str(status))
            response.close()
        response = client.head("/200")
        response.close()
        rows = self.rows()
        self.assertEqual(len(rows), 8)
        self.assertEqual([row["status"] for row in rows], [200, 304, 301, 400, 404, 405, 500, 200])
        self.assertEqual(rows[-1]["response_bytes"], 0)
        self.assertEqual(rows[-2]["validity"], "valid")

    def test_proxy_headers_untrusted_and_trusted_ipv6(self):
        request_id = "c" * 32
        for trusted in (False, True):
            client = self.make_client(("127.0.0.1/32",) if trusted else ())
            response = client.get(
                "/200",
                headers={"X-Forwarded-For": "2001:db8::2", "X-Request-ID": request_id},
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            )
            response.close()
        untrusted, trusted = self.rows()
        self.assertIsNone(untrusted["edge_request_id"])
        self.assertEqual(untrusted["address_family"], 4)
        self.assertEqual(trusted["edge_request_id"], request_id)
        self.assertEqual(trusted["address_family"], 6)
        self.assertNotEqual(untrusted["address_token"], trusted["address_token"])

    def test_stream_interruption_keeps_actual_header_status(self):
        def app(environ, start_response):
            start_response("200 OK", [])

            def stream():
                yield b"one"
                raise RuntimeError("stream failed")

            return stream()

        environ = {"PATH_INFO": "/uk", "REQUEST_METHOD": "GET", "REMOTE_ADDR": "127.0.0.1"}
        stream = RequestAnalyticsMiddleware(app, self.store)(environ, lambda *args: None)
        self.assertEqual(next(stream), b"one")
        with self.assertRaises(RuntimeError):
            next(stream)
        stream.close()
        row = self.rows()[0]
        self.assertEqual(row["status"], 200)
        self.assertEqual(row["outcome"], "interrupted")
        self.assertEqual(row["response_bytes"], 3)
        self.assertEqual(len(self.rows()), 1)

    def test_wsgi_application_exception_is_captured(self):
        def app(environ, start_response):
            raise RuntimeError("application failure")

        with self.assertRaises(RuntimeError):
            RequestAnalyticsMiddleware(app, self.store)(
                {"PATH_INFO": "/uk", "REQUEST_METHOD": "GET"}, lambda *args: None
            )
        self.assertEqual(self.rows()[0]["status"], 500)
        self.assertIn("app_exception", self.rows()[0]["reasons"])


if __name__ == "__main__":
    unittest.main()
