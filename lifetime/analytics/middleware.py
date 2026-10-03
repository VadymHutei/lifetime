"""WSGI capture includes HEAD, static, errors and interrupted iterables."""

from datetime import datetime, timezone
import time
import uuid

from .sanitize import safe_request_id, trusted_address


class RequestAnalyticsMiddleware:
    def __init__(self, app, store, trusted_proxy_cidrs=(), app_version=None):
        self.app = app
        self.store = store
        self.trusted_proxy_cidrs = tuple(trusted_proxy_cidrs)
        if app_version is None:
            from lifetime.version import get_version

            app_version = get_version()
        self.app_version = app_version
        # Reject mistakes at configuration time, outside any request.
        import ipaddress

        for cidr in self.trusted_proxy_cidrs:
            ipaddress.ip_network(cidr)

    def __call__(self, environ, start_response):
        started = time.perf_counter()
        address, _, proxy_trusted = trusted_address(environ, self.trusted_proxy_cidrs)
        edge_id = safe_request_id(environ.get("HTTP_X_REQUEST_ID")) if proxy_trusted else None
        event = {
            "event_id": uuid.uuid4().hex,
            "edge_request_id": edge_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "app",
            "method": environ.get("REQUEST_METHOD", "GET"),
            "path": environ.get("PATH_INFO", "/"),
            "query_string": environ.get("QUERY_STRING", ""),
            "user_agent": environ.get("HTTP_USER_AGENT", ""),
            "referer": environ.get("HTTP_REFERER", ""),
            "ip": address,
            "app_version": self.app_version,
            "flags": ["proxy_trusted"] if proxy_trusted else [],
        }
        state = {"status": 500, "bytes": 0, "recorded": False, "interrupted": False}

        def capture_start_response(status, headers, exc_info=None):
            state["status"] = int(status.split(" ", 1)[0])
            write = start_response(status, headers, exc_info)

            def capture_write(data):
                state["bytes"] += len(data)
                return write(data)

            return capture_write

        def finish():
            if state["recorded"]:
                return
            state["recorded"] = True
            event.update(
                status=state["status"],
                response_bytes=state["bytes"],
                duration_ms=(time.perf_counter() - started) * 1000,
                validity=environ.get("lifetime.validity"),
                route=environ.get("lifetime.route"),
                endpoint=environ.get("lifetime.endpoint"),
                locale=environ.get("lifetime.locale"),
                dataset_id=environ.get("lifetime.dataset_id"),
                safe_path=environ.get("lifetime.safe_path"),
            )
            if state["interrupted"]:
                event.update(outcome="interrupted", reasons=["stream_interrupted"])
            try:
                self.store.record(event)
            except Exception:
                # Also protect against a replaced/operator-provided store.
                try:
                    self.store._signal("dropped_event unexpected_logger_failure", dropped=True)
                except Exception:
                    pass

        try:
            iterable = self.app(environ, capture_start_response)
        except BaseException:
            event["reasons"] = ["app_exception"]
            finish()
            raise

        class CapturedIterable:
            def __init__(self):
                self.iterator = iter(iterable)
                self.complete = False

            def __iter__(self):
                return self

            def __next__(self):
                try:
                    data = next(self.iterator)
                    state["bytes"] += len(data)
                    return data
                except StopIteration:
                    self.complete = True
                    finish()
                    raise
                except BaseException:
                    state["interrupted"] = True
                    finish()
                    raise

            def close(self):
                if not self.complete:
                    state["interrupted"] = True
                try:
                    if hasattr(iterable, "close"):
                        iterable.close()
                except BaseException:
                    state["interrupted"] = True
                    raise
                finally:
                    finish()

        return CapturedIterable()
