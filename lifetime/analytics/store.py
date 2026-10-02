"""Short SQL transactions with a durable, process-safe disk fallback."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import threading
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from .sanitize import Rules, sanitize_event
from .schema import daily, events


class AnalyticsStore:
    def __init__(
        self,
        engine,
        spool_dir,
        secret,
        app_version=None,
        retain_days=90,
        raw_ip_days=7,
        aggregate_days=365,
        store_raw_ip=False,
        rules=None,
    ):
        self.engine = engine
        self.spool_dir = Path(spool_dir)
        if not secret:
            raise ValueError("Analytics HMAC secret must not be empty")
        self.secret = secret
        if app_version is None:
            from lifetime.version import get_version

            app_version = get_version()
        self.app_version = app_version
        self.retain_days = max(0, int(retain_days))
        self.raw_ip_days = max(0, int(raw_ip_days))
        self.aggregate_days = max(0, int(aggregate_days))
        self.store_raw_ip = bool(store_raw_ip and self.raw_ip_days)
        self.rules = rules or Rules()
        self.dropped_events = 0
        self.spooled_events = 0
        self._metric_lock = threading.Lock()

    def migrate(self):
        """Explicit CLI operation; never called by record() or factory import."""
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[2] / "migrations" / "analytics")
        )
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def _signal(self, message, dropped=False):
        if dropped:
            with self._metric_lock:
                self.dropped_events += 1
        try:
            # No exception text: drivers/filesystem errors can contain secrets.
            print("lifetime.analytics " + message, file=sys.stderr)
        except Exception:
            pass

    def _safe(self, event):
        version = event.get("app_version", self.app_version)
        # Old spool/edge versions are useful; allow only SemVer vocabulary.
        import re

        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?(?:\+[a-zA-Z0-9.-]+)?", str(version)):
            version = self.app_version
        return sanitize_event(event, self.secret, version, self.store_raw_ip, self.rules)

    def _insert(self, event):
        """Upsert stable edge IDs; preserve app annotations and final edge outcome."""
        with self.engine.begin() as connection:
            try:
                with connection.begin_nested():
                    connection.execute(insert(events).values(**event))
                return "inserted"
            except IntegrityError:
                current = (
                    connection.execute(select(events).where(events.c.event_id == event["event_id"]))
                    .mappings()
                    .first()
                )
                if current is None:
                    raise
                if not event["edge_request_id"]:
                    return "duplicate"
                current = dict(current)
                if event["source"] == "edge":
                    # Nginx logs the final client-visible status after WSGI exits.
                    merged = {
                        "status": event["status"],
                        "response_bytes": event["response_bytes"],
                        "duration_ms": event["duration_ms"],
                        "outcome": event["outcome"],
                        "reasons": sorted(set(current["reasons"] + ["edge_status"])),
                        "flags": sorted(
                            set(current["flags"] + (["edge_only"] if current["source"] == "edge" else []))
                        ),
                    }
                elif current["source"] == "edge":
                    merged = {
                        **event,
                        "status": current["status"],
                        "response_bytes": current["response_bytes"],
                        "duration_ms": current["duration_ms"],
                        "outcome": current["outcome"],
                        "flags": sorted(set(event["flags"]) - {"edge_only"}),
                        "reasons": sorted(set(event["reasons"] + ["edge_status"])),
                    }
                else:
                    return "duplicate"
                connection.execute(
                    update(events).where(events.c.event_id == event["event_id"]).values(**merged)
                )
                return "merged"

    def _spool(self, event):
        """One atomic file per event avoids shared append/partial-line races."""
        self.spool_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        filename = uuid.uuid4().hex
        temporary = self.spool_dir / (filename + ".tmp")
        target = self.spool_dir / (filename + ".json")
        payload = json.dumps(event, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > 16384:
            raise ValueError("Sanitized spool event exceeded bound")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            # Persist the rename on POSIX; Windows has no portable dir fsync.
            if os.name != "nt":
                directory = os.open(self.spool_dir, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        with self._metric_lock:
            self.spooled_events += 1

    def record(self, event):
        """Fail-open entrypoint; no raw data reaches any persistence path."""
        try:
            safe = self._safe(event)
        except Exception:
            self._signal("dropped_event sanitize_failed", dropped=True)
            return "dropped"
        if not self.retain_days:
            return "disabled"
        try:
            return self._insert(safe)
        except Exception:
            try:
                self._spool(safe)
                self._signal("database_unavailable event_spooled")
                return "spooled"
            except Exception:
                self._signal("dropped_event persistence_failed", dropped=True)
                return "dropped"

    def replay(self):
        result = {"inserted": 0, "merged": 0, "duplicate": 0, "failed": 0, "expired": 0, "corrupt": 0}
        if not self.spool_dir.exists():
            return result
        now = datetime.now(timezone.utc)
        # A crashed worker's claimed file is recovered after a bounded lease.
        for stale in self.spool_dir.glob("*.claim"):
            if now.timestamp() - stale.stat().st_mtime > 300:
                try:
                    stale.rename(stale.with_suffix(".json"))
                except OSError:
                    pass
        for path in sorted(self.spool_dir.glob("*.json")):
            claimed = path.with_suffix(".claim")
            try:
                path.rename(claimed)
                os.utime(claimed, None)
            except OSError:
                continue
            try:
                if claimed.stat().st_size > 16384:
                    raise ValueError("Oversized spool")
                safe = self._safe(json.loads(claimed.read_text(encoding="utf-8")))
                timestamp = datetime.fromisoformat(safe["timestamp"])
                if not self.retain_days or timestamp < now - timedelta(days=self.retain_days):
                    result["expired"] += 1
                else:
                    if timestamp < now - timedelta(days=self.raw_ip_days):
                        safe["raw_ip"] = None
                    action = self._insert(safe)
                    result[action] += 1
                claimed.unlink()
            except ValueError, TypeError, json.JSONDecodeError:
                result["corrupt"] += 1
                self._signal("dropped_event corrupt_spool", dropped=True)
                claimed.unlink(missing_ok=True)
            except Exception:
                result["failed"] += 1
                try:
                    claimed.rename(path)
                except OSError:
                    pass
        # Atomic temporary files never contain an acknowledged event. Stale
        # files signal interrupted writes and are discarded, not parsed.
        for temporary in self.spool_dir.glob("*.tmp"):
            if now.timestamp() - temporary.stat().st_mtime > 300:
                temporary.unlink(missing_ok=True)
                result["corrupt"] += 1
                self._signal("dropped_event interrupted_spool_write", dropped=True)
        return result

    def purge(self, now=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        event_cutoff = (now - timedelta(days=self.retain_days)).isoformat(timespec="milliseconds")
        raw_cutoff = (now - timedelta(days=self.raw_ip_days)).isoformat(timespec="milliseconds")
        aggregate_cutoff = (now - timedelta(days=self.aggregate_days)).date().isoformat()
        result = {"events": 0, "raw_ips": 0, "aggregates": 0, "spool_events": 0, "spool_raw_ips": 0}
        try:
            self._purge_database(event_cutoff, raw_cutoff, aggregate_cutoff, result)
        except Exception:
            result["database_failed"] = 1
            # SQL transaction rolled back; do not report tentative deletion counts.
            result.update(events=0, raw_ips=0, aggregates=0)
            self._signal("database_retention_failed")
        # Retention also applies to durable files during a DB outage. Replay is
        # not required to remove stale detailed/raw data.
        if self.spool_dir.exists():
            # Recover abandoned claims before retention. Active replayers own
            # short leases and will enforce the same policy before insertion.
            for claimed in self.spool_dir.glob("*.claim"):
                try:
                    if now.timestamp() - claimed.stat().st_mtime > 300:
                        claimed.rename(claimed.with_suffix(".json"))
                except OSError:
                    self._signal("spool_retention_failed")
            for temporary in self.spool_dir.glob("*.tmp"):
                try:
                    if now.timestamp() - temporary.stat().st_mtime > 300:
                        temporary.unlink()
                        self._signal("dropped_event interrupted_spool_write", dropped=True)
                except OSError:
                    self._signal("spool_retention_failed")
            for path in self.spool_dir.glob("*.json"):
                try:
                    safe = self._safe(json.loads(path.read_text(encoding="utf-8")))
                    if safe["timestamp"] < event_cutoff or not self.retain_days:
                        path.unlink()
                        result["spool_events"] += 1
                    elif safe["raw_ip"] and safe["timestamp"] < raw_cutoff:
                        safe["raw_ip"] = None
                        self._spool(safe)
                        path.unlink()
                        result["spool_raw_ips"] += 1
                except OSError, ValueError, TypeError:
                    self._signal("spool_retention_failed")
        return result

    def _purge_database(self, event_cutoff, raw_cutoff, aggregate_cutoff, result):
        with self.engine.begin() as connection:
            # Fold only rows about to expire, once, in the same transaction as
            # deletion. This preserves earlier counts across repeated purges.
            day = func.substr(events.c.timestamp, 1, 10)
            dimensions = [events.c.validity, events.c.client_class, events.c.security_class, events.c.outcome]
            expired = events.c.timestamp < event_cutoff
            if self.aggregate_days:
                rows = connection.execute(
                    select(day.label("day"), *dimensions, func.count().label("count"))
                    .where(expired)
                    .group_by(day, *dimensions)
                ).mappings()
                for row in rows:
                    if row["day"] < aggregate_cutoff:
                        continue
                    keys = {
                        key: row[key]
                        for key in ("day", "validity", "client_class", "security_class", "outcome")
                    }
                    where = and_(*(daily.c[key] == value for key, value in keys.items()))
                    found = connection.execute(select(daily.c.count).where(where)).scalar_one_or_none()
                    if found is None:
                        connection.execute(insert(daily).values(**dict(row)))
                    else:
                        connection.execute(update(daily).where(where).values(count=found + row["count"]))
            result["events"] = connection.execute(delete(events).where(expired)).rowcount
            result["raw_ips"] = connection.execute(
                update(events)
                .where(events.c.raw_ip.is_not(None), events.c.timestamp < raw_cutoff)
                .values(raw_ip=None)
            ).rowcount
            result["aggregates"] = connection.execute(
                delete(daily).where(daily.c.day < aggregate_cutoff if self.aggregate_days else True)
            ).rowcount

    def report(self, group="overview", since=None, until=None, limit=100):
        predicates = {
            "valid": events.c.validity == "valid",
            "bots": events.c.client_class.in_(("claimed_bot", "verified_bot")),
            "invalid": events.c.validity == "invalid",
            "suspicious": events.c.security_class == "suspicious",
            "normal": and_(
                events.c.validity == "valid",
                events.c.security_class == "normal",
                events.c.client_class.in_(("unknown", "likely_human")),
            ),
        }
        aliases = {"bot": "bots", "security": "suspicious", "all": "overview"}
        group = aliases.get(group, group)
        if group not in {"overview", "daily", *predicates}:
            raise ValueError("Unknown report group")
        filters = []
        for value, comparison in ((since, "since"), (until, "until")):
            if value:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                iso = parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")
                filters.append(
                    events.c.timestamp >= iso if comparison == "since" else events.c.timestamp < iso
                )
        with self.engine.connect() as connection:
            if group == "daily":
                aggregates = [
                    dict(row)
                    for row in connection.execute(
                        select(daily).order_by(daily.c.day.desc()).limit(max(1, min(1000, int(limit))))
                    ).mappings()
                ]
                return {
                    "group": group,
                    "rows": aggregates,
                    "note": "Expired detailed events only; current events remain in overview.",
                }
            count = connection.execute(
                select(func.count())
                .select_from(events)
                .where(*filters, *([predicates[group]] if group in predicates else []))
            ).scalar_one()
            if group == "overview":
                dimensions = [
                    events.c.validity,
                    events.c.client_class,
                    events.c.security_class,
                    events.c.outcome,
                ]
                matrix = [
                    dict(row)
                    for row in connection.execute(
                        select(*dimensions, func.count().label("count")).where(*filters).group_by(*dimensions)
                    ).mappings()
                ]
                return {
                    "group": group,
                    "total": count,
                    "matrix": matrix,
                    "dropped_events_process": self.dropped_events,
                    "spooled_events_process": self.spooled_events,
                    "overlap_note": "Matrix cells are exclusive. valid/bots/invalid/suspicious reports overlap and must not be added.",
                }
            rows = [
                dict(row)
                for row in connection.execute(
                    select(events)
                    .where(*filters, predicates[group])
                    .order_by(events.c.timestamp.desc())
                    .limit(max(1, min(1000, int(limit))))
                ).mappings()
            ]
            return {
                "group": group,
                "total": count,
                "rows": rows,
                "overlap_note": "Reports overlap across independent dimensions.",
            }

    def export(self, **kwargs):
        return self.report(**kwargs)

    def ingest_edge(self, path):
        """Read sanitized JSONL; only typed allowlisted fields enter record()."""
        result = {
            "inserted": 0,
            "merged": 0,
            "duplicate": 0,
            "spooled": 0,
            "dropped": 0,
            "disabled": 0,
            "invalid_lines": 0,
        }
        with Path(path).open("r", encoding="utf-8") as stream:
            for line in stream:
                if len(line) > 16384:
                    result["invalid_lines"] += 1
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("Not a mapping")
                    from .sanitize import safe_request_id

                    if not safe_request_id(event.get("edge_request_id")):
                        raise ValueError("Missing edge identifier")
                    event["source"] = "edge"
                    event["duration_ms"] = float(event.get("duration_seconds", 0)) * 1000
                    result[self.record(event)] += 1
                except ValueError, TypeError, json.JSONDecodeError:
                    result["invalid_lines"] += 1
        return result
