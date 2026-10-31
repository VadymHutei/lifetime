"""Operator acceptance over real HTTPS, using invented DOB and redaction probes."""

import json
import os
from pathlib import Path
import socket
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

from sqlalchemy import select, text

from lifetime import create_app
from lifetime.analytics.schema import events
from lifetime.version import get_version


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


app = create_app()
store = app.extensions["analytics"]
origin = app.config["SERVICE_URL"]
# Verify the same certificate/SNI through the private proxy from app's network.
# Public routing is checked separately from the operator's external connection.
if private_proxy := os.environ.get("SMOKE_PROXY_IP"):
    original_resolver = socket.getaddrinfo

    def resolve_proxy(host, port, *args, **kwargs):
        if host == "lifetime.ukubuka.net":
            host = private_proxy
        return original_resolver(host, port, *args, **kwargs)

    socket.getaddrinfo = resolve_proxy
opener = build_opener(NoRedirect)
checks = []
request_ids = []


def request(path, expected=200, *, method="GET", data=None, headers=None):
    req = Request(origin + path, data=data, method=method, headers=headers or {})
    try:
        response = opener.open(req, timeout=20)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read().decode("utf-8")
        assert response.status == expected, (path, response.status)
        edge_id = response.headers.get("X-Request-ID")
        assert edge_id and len(edge_id) == 32, (path, "missing edge id")
        request_ids.append(edge_id)
        checks.append({"method": method, "path": path.split("?")[0], "status": response.status})
        return body, response.headers


for locale in ("uk", "en"):
    body, _ = request("/" + locale)
    assert "https://lifetime.ukubuka.net/" + locale in body
    assert body.count("<h1") == 1
    assert get_version() in body
request("/readyz")
request("/static/style.css")
request("/uk", method="HEAD")
_, headers = request("/ukr", 301)
assert headers["Location"] == "/uk"
request("/rus", 410)
request("/missing-acceptance-page", 404)
request("/uk", 405, method="POST", data=b"")
form = urlencode({"birth_date": "1999-12-30", "country": "UKR", "sex": "total"}).encode()
body, headers = request("/uk/result", method="POST", data=form)
assert 'name="birth_date"' in body
assert "noindex" in headers["X-Robots-Tag"]
assert headers["Cache-Control"] == "no-store"
body, _ = request("/uk/result?birth_date=1999-12-30&admin_key=ACCEPTANCE_PRIVATE_MARKER")
assert "1999-12-30" not in body
request("/private-1999-12-30-ACCEPTANCE_PRIVATE_MARKER", 404)
request("/uk/result", 413, method="POST", data=b"x" * 20000)
_, headers = request(
    "/uk",
    headers={"X-Forwarded-For": "203.0.113.123", "X-Request-ID": "a" * 32},
)
assert headers["X-Request-ID"] != "a" * 32
body, _ = request("/sitemap.xml")
urls = [item.text for item in ET.fromstring(body).findall("{*}url/{*}loc")]
assert len(urls) == 458
assert all(url.startswith(origin + "/") and "/result" not in url for url in urls)
request("/robots.txt")

time.sleep(1)
edge_file = Path("/var/lib/lifetime/edge/edge.jsonl")
edge_content = edge_file.read_text()
for value in ("1999-12-30", "ACCEPTANCE_PRIVATE_MARKER", "birth_date", "203.0.113.123"):
    assert value not in edge_content, "sensitive edge log value"
first = store.ingest_edge(edge_file)
assert first["dropped"] == first["invalid_lines"] == first["disabled"] == first["spooled"] == 0
store.ingest_edge(edge_file)
with app.extensions["analytics_engine"].connect() as connection:
    rows = list(
        connection.execute(select(events).where(events.c.edge_request_id.in_(request_ids))).mappings()
    )
    assert len(rows) == len(request_ids), (len(rows), len(request_ids))
    assert len({row["event_id"] for row in rows}) == len(request_ids)
    serialized = json.dumps([dict(row) for row in rows])
    for value in ("1999-12-30", "ACCEPTANCE_PRIVATE_MARKER", "birth_date", "203.0.113.123"):
        assert value not in serialized, "sensitive analytics value"
    assert all(row["raw_ip"] is None for row in rows)
    assert all("proxy_trusted" in row["flags"] for row in rows if row["source"] == "app")
    assert any(row["status"] == 413 and row["source"] == "edge" for row in rows)
    assert connection.scalar(text("SELECT version_num FROM alembic_reference_version")) == "reference_0002"
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "analytics_0003"
assert len(app.extensions["reference"].list_locations("uk")) == 225
assert store.replay()["failed"] == 0
assert not list(Path("/var/lib/lifetime/spool").glob("*.json"))
print(
    json.dumps(
        {"checks": checks, "sitemap_urls": len(urls), "deduplicated_events": len(rows), "privacy": "passed"},
        indent=2,
    )
)
