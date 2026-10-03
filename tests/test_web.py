"""HTTP acceptance tests against isolated migrated/imported SQLite databases."""

from datetime import date
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from sqlalchemy import select
from werkzeug.datastructures import MultiDict

from lifetime import create_app
from lifetime.analytics.schema import events
from lifetime.version import get_version


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://lifetime.example"


class Document(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.h1 = 0
        self.title = ""
        self.links = []
        self.meta = []
        self.inputs = []
        self.forms = []
        self.buttons = []
        self.options = []
        self.schemas = []
        self.language = None
        self._capture = None
        self._text = ""
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.language = attrs.get("lang")
        if tag == "h1":
            self.h1 += 1
        for target, name in [
            ("link", "links"),
            ("meta", "meta"),
            ("input", "inputs"),
            ("form", "forms"),
            ("button", "buttons"),
            ("option", "options"),
        ]:
            if tag == target:
                getattr(self, name).append(attrs)
        if tag == "title" or (tag == "script" and attrs.get("type") == "application/ld+json"):
            self._capture = tag
            self._text = ""

    def handle_data(self, data):
        if self._capture:
            self._text += data

    def handle_endtag(self, tag):
        if tag == self._capture:
            if tag == "title":
                self.title = self._text
            else:
                self.schemas.append(json.loads(self._text))
            self._capture = None

    def canonical(self):
        return [item["href"] for item in self.links if item.get("rel") == "canonical"]


class WebAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = (ROOT / ".artifacts" / ("web-tests-" + uuid4().hex)).resolve()
        cls.directory.mkdir(parents=True)
        cls.app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": cls.directory,
                "REFERENCE_DATABASE_URL": f"sqlite:///{cls.directory / 'reference.sqlite3'}",
                "ANALYTICS_DATABASE_URL": f"sqlite:///{cls.directory / 'analytics.sqlite3'}",
                "SERVICE_URL": ORIGIN,
                "TODAY": lambda: date(2026, 10, 3),
                "ANALYTICS_SECRET": "web-tests-independent-secret-0123456789",
                "ANALYTICS_RETENTION_DAYS": 37,
                "ANALYTICS_AGGREGATE_DAYS": 150,
                "ANALYTICS_STORE_RAW_IP": False,
            }
        )
        cls.client = cls.app.test_client()
        runner = cls.app.test_cli_runner()
        for arguments in [("migrate",), ("import-data",)]:
            result = runner.invoke(args=list(arguments))
            if result.exit_code:
                raise AssertionError(result.output) from result.exception
        cls.repository = cls.app.extensions["reference"]

    @classmethod
    def tearDownClass(cls):
        for name in ("reference_engine", "analytics_engine"):
            cls.app.extensions[name].dispose()
        # Delete only the UUID directory created by this class, inside .artifacts.
        if cls.directory.parent == (ROOT / ".artifacts").resolve() and cls.directory.name.startswith(
            "web-tests-"
        ):
            shutil.rmtree(cls.directory)

    def get(self, path, **kwargs):
        return self.client.get(path, base_url=ORIGIN, buffered=True, **kwargs)

    def post(self, data=None, path="/uk/result", **kwargs):
        return self.client.post(
            path,
            data=data or {"birth_date": "2000-02-29", "country": "UKR", "sex": "total"},
            base_url=ORIGIN,
            buffered=True,
            **kwargs,
        )

    def test_public_pages_metadata_and_version(self):
        for locale in ("uk", "en"):
            for suffix in ("", "/countries", "/methodology", "/privacy"):
                with self.subTest(locale=locale, suffix=suffix):
                    response = self.get("/" + locale + suffix)
                    self.assertEqual(response.status_code, 200)
                    document = Document(response)
                    self.assertEqual(document.h1, 1)
                    self.assertEqual(document.language, locale)
                    self.assertEqual(document.canonical(), [ORIGIN + "/" + locale + suffix])
                    self.assertEqual(document.title.count("LifeTime"), 1)
                    self.assertTrue(document.schemas)
                    self.assertIn(get_version(), response.get_data(as_text=True))
                    alternate = {
                        item.get("hreflang"): item["href"]
                        for item in document.links
                        if item.get("rel") == "alternate"
                    }
                    self.assertEqual(alternate["uk"], ORIGIN + "/uk" + suffix)
                    self.assertEqual(alternate["en"], ORIGIN + "/en" + suffix)
                    self.assertIn("x-default", alternate)
                    self.assertTrue(any(item.get("property") == "og:title" for item in document.meta))
                    if not suffix:
                        self.assertEqual(
                            next(item for item in document.schemas if item["@type"] == "WebApplication")[
                                "softwareVersion"
                            ],
                            get_version(),
                        )

    def test_every_public_location_has_unique_localized_indexable_page(self):
        for locale in ("uk", "en"):
            locations = self.repository.list_locations(locale)
            self.assertEqual(len(locations), 225)
            titles = set()
            for location in locations:
                with self.subTest(locale=locale, code=location["code"]):
                    path = f"/{locale}/{location['slug']}"
                    response = self.get(path)
                    self.assertEqual(response.status_code, 200)
                    document = Document(response)
                    self.assertEqual(document.h1, 1)
                    self.assertEqual(document.canonical(), [ORIGIN + path])
                    self.assertNotIn(document.title, titles)
                    titles.add(document.title)
                    self.assertNotIn("noindex", response.headers.get("X-Robots-Tag", ""))
                    self.assertTrue(
                        location["name"] in unescape(response.get_data(as_text=True)), location["name"]
                    )
                    self.assertIn("2024", response.get_data(as_text=True))

    def test_sitemap_only_public_urls_and_real_source(self):
        response = self.get("/sitemap.xml")
        root = ET.fromstring(response.data)
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = root.findall("s:url", namespace)
        self.assertEqual(len(urls), 458)
        addresses = [entry.find("s:loc", namespace).text for entry in urls]
        self.assertEqual(len(set(addresses)), len(addresses))
        self.assertTrue(
            all(address.startswith(ORIGIN + "/") and "/result" not in address for address in addresses)
        )
        self.assertTrue(
            all(
                entry.find("s:lastmod", namespace).text == self.app.config["CONTENT_UPDATED"]
                for entry in urls
            )
        )
        robots = self.get("/robots.txt").get_data(as_text=True)
        self.assertIn("Sitemap: " + ORIGIN + "/sitemap.xml", robots)
        self.assertNotIn("Disallow: /uk/result", robots)

    def test_valid_result_preserves_form_and_language_without_dob_urls(self):
        for locale in ("uk", "en"):
            response = self.post(path=f"/{locale}/result")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn("noindex", response.headers["X-Robots-Tag"])
            document = Document(response)
            self.assertFalse(document.canonical())
            self.assertEqual(
                next(field for field in document.inputs if field.get("id") == "birth_date")["value"],
                "2000-02-29",
            )
            self.assertTrue(
                any(option.get("value") == "UKR" and "selected" in option for option in document.options)
            )
            text = response.get_data(as_text=True)
            self.assertIn('id="result"', text)
            self.assertIn('formaction="/uk/result"', text)
            self.assertIn('formaction="/en/result"', text)
            self.assertNotIn('style="', text)
            self.assertTrue(all("2000-02-29" not in item.get("href", "") for item in document.links))
            self.assertIn("World Bank", text)
            self.assertIn("2024", text)

    def test_language_buttons_submit_live_calculator_form_without_js(self):
        for response in (
            self.get("/uk"),
            self.get("/en"),
            self.get("/uk/ukraine"),
            self.post(),
            self.post({"birth_date": "bad", "country": "UKR", "sex": "total"}),
        ):
            document = Document(response)
            forms = [form for form in document.forms if form.get("id") == "calculator-form"]
            self.assertEqual(len(forms), 1)
            self.assertEqual(forms[0]["method"], "post")
            associated = [
                button
                for button in document.buttons
                if button.get("form") == "calculator-form" and button.get("type") == "submit"
            ]
            self.assertTrue(associated)
            self.assertEqual(associated[0]["formaction"], f"/{document.language}/result")
            self.assertIn("hidden", associated[0])
            buttons = [
                button
                for button in document.buttons
                if button.get("formaction") in {"/uk/result", "/en/result"}
                and "language" in button.get("class", "").split()
            ]
            self.assertEqual(len(buttons), 2)
            self.assertTrue(
                all(
                    button.get("form") == "calculator-form" and "formnovalidate" in button
                    for button in buttons
                )
            )
            self.assertFalse(
                any(
                    field.get("type") == "hidden" and field.get("name") == "birth_date"
                    for field in document.inputs
                )
            )
        # A language POST carries current edits rather than a stale result copy.
        response = self.post(
            {"birth_date": "2001-03-04", "country": "USA", "sex": "female"}, path="/en/result"
        )
        self.assertEqual(response.status_code, 200)
        document = Document(response)
        self.assertEqual(document.language, "en")
        self.assertEqual(
            next(item for item in document.inputs if item.get("id") == "birth_date")["value"], "2001-03-04"
        )
        self.assertTrue(any(item.get("value") == "USA" and "selected" in item for item in document.options))

    def test_validation_keeps_input_and_never_silently_changes_country(self):
        cases = [
            ("birth_date", "2027-01-01"),
            ("birth_date", "2025-02-29"),
            ("birth_date", "bad"),
            ("country", "UNKNOWN"),
            ("sex", "other"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = {"birth_date": "2000-02-29", "country": "UKR", "sex": "total", field: value}
                response = self.post(data)
                self.assertEqual(response.status_code, 400)
                text = response.get_data(as_text=True)
                self.assertIn('role="alert"', text)
                self.assertIn("no-store", response.headers["Cache-Control"])
                document = Document(response)
                if field == "country":
                    self.assertEqual(
                        [option.get("value") for option in document.options if "selected" in option], [""]
                    )
                elif field == "birth_date":
                    self.assertEqual(
                        next(item for item in document.inputs if item.get("id") == "birth_date")["value"],
                        value,
                    )
        for field in ("birth_date", "country", "sex"):
            data = MultiDict(
                [("birth_date", "2000-02-29"), ("country", "UKR"), ("sex", "total"), (field, "duplicate")]
            )
            self.assertEqual(self.post(data).status_code, 400)

    def test_malformed_method_and_payload_are_controlled(self):
        self.assertEqual(self.post({"birth_date": "not-a-date"}).status_code, 400)
        response = self.client.put("/uk", base_url=ORIGIN)
        self.assertEqual(response.status_code, 405)
        self.assertIn("GET", response.headers.get("Allow", ""))
        response = self.post({"birth_date": "x" * 20000})
        self.assertEqual(response.status_code, 413)
        self.assertIn("noindex", response.headers["X-Robots-Tag"])

    def test_legacy_redirect_results_and_retained_unavailable(self):
        self.assertEqual(self.get("/ukr").headers["Location"], "/uk")
        self.assertEqual(self.get("/eng").headers["Location"], "/en")
        selected = self.repository.legacy_location("181", "uk")
        response = self.get("/ukr/181")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/uk/" + selected["slug"])
        for sex in ("1", "2", "3"):
            response = self.get(
                "/ukr/result", query_string={"birth_date": "2000-02-29", "country": "181", "sex": sex}
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Location", response.headers)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        aliases = json.loads((ROOT / "data/life_expectancy/legacy_aliases.json").read_text(encoding="utf-8"))
        unavailable = [item for item in aliases if item["disposition"] == "retained_unavailable"]
        self.assertEqual(len(unavailable), 8)
        for alias in unavailable:
            response = self.get("/uk/" + alias["legacy_alias"])
            self.assertEqual(response.status_code, 200)
            document = Document(response)
            self.assertFalse(document.canonical())
            self.assertTrue(
                any(item.get("name") == "robots" and "noindex" in item["content"] for item in document.meta)
            )
        self.assertEqual(self.get("/uk/unknown-geography").status_code, 404)
        for path in ("/rus", "/rus/result", "/rus/ukraine", "/translations", "/translations/delete"):
            self.assertEqual(self.get(path).status_code, 410)

    def test_search_and_privacy_live_config(self):
        response = self.get("/en/countries?q=Ukraine")
        self.assertEqual(response.status_code, 200)
        document = Document(response)
        self.assertFalse(document.canonical())
        self.assertIn("noindex", response.get_data(as_text=True))
        self.assertIn("Ukraine", response.get_data(as_text=True))
        text = self.get("/en/privacy").get_data(as_text=True)
        self.assertIn("Event retention, days: 37", text)
        self.assertIn("Aggregate retention, days: 150", text)
        self.assertIn("Raw IP storage is disabled.", text)

    def test_host_injection_is_rejected(self):
        response = self.client.get("/uk", base_url="https://attacker.invalid")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("https://attacker.invalid", response.get_data(as_text=True))

    def test_http_analytics_captures_outcomes_without_dob(self):
        engine = self.app.extensions["analytics_engine"]
        with engine.connect() as connection:
            prior = set(connection.execute(select(events.c.event_id)).scalars())
        self.post()
        self.get("/uk", headers={"User-Agent": "ExampleBot/1.0"})
        self.get("/missing?birth_date=2000-02-29&password=secret")
        self.get("/static/style.css")
        self.client.head("/uk", base_url=ORIGIN, buffered=True)
        with engine.connect() as connection:
            records = [
                dict(row)
                for row in connection.execute(select(events)).mappings()
                if row["event_id"] not in prior
            ]
        self.assertEqual(len(records), 5)
        self.assertEqual(len({row["event_id"] for row in records}), 5)
        self.assertTrue(any(row["method"] == "POST" and row["validity"] == "valid" for row in records))
        self.assertTrue(any("bot" in row["client_class"] for row in records))
        self.assertTrue(any(row["status"] == 404 and row["validity"] == "invalid" for row in records))
        serialized = json.dumps(records, default=str)
        self.assertNotIn("2000-02-29", serialized)
        self.assertNotIn("secret", serialized)
        self.assertTrue(all(row["raw_ip"] is None for row in records))
        self.assertTrue(all(row["app_version"] == get_version() for row in records))


if __name__ == "__main__":
    unittest.main()
