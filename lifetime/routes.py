"""Server-rendered public routes and explicit legacy URL compatibility."""

from datetime import datetime
import xml.etree.ElementTree as ET

from flask import Blueprint, abort, current_app, redirect, render_template, request
from sqlalchemy.exc import SQLAlchemyError

from lifetime.services.calculator import calculate, validate_birth_date
from lifetime.services.seo import metadata

web = Blueprint("web", __name__)
LOCALES = {"uk", "en"}


def repository():
    return current_app.extensions["reference"]


def today():
    clock = current_app.config.get("TODAY")
    return clock() if callable(clock) else datetime.now(current_app.config["TIMEZONE"]).date()


def dataset():
    try:
        data = repository().active_dataset()
    except SQLAlchemyError:
        abort(503)
    if not data:
        abort(503)
    request.environ["lifetime.dataset_id"] = str(data["id"])
    return data


def page(template, locale, kind="home", suffix="", **values):
    noindex = values.pop("noindex", False)
    data = dataset()
    locations = values.pop("locations", None)
    if locations is None:
        locations = repository().list_locations(locale)
    selected = values.pop("selected", None) or repository().get_location("WLD", locale)
    form = values.pop("form", {"birth_date": "", "country": selected["code"], "sex": "total"})
    context = metadata(
        current_app.config["SERVICE_URL"],
        locale,
        kind,
        suffix,
        selected,
        current_app.config["APP_VERSION"],
        noindex,
        data,
    )
    context.update(
        locale=locale,
        locations=locations,
        selected=selected,
        form=form,
        errors={},
        result=None,
        today=today().isoformat(),
        dataset=data,
        content_kind=kind,
    )
    context.update(values)
    request.environ["lifetime.validity"] = "valid"
    return render_template(template, **context)


@web.get("/")
def root():
    return redirect("/uk", 302)


@web.get("/healthz")
def health():
    return {"status": "ok", "version": current_app.config["APP_VERSION"]}


@web.get("/readyz")
def ready():
    try:
        active = repository().active_dataset()
        with current_app.extensions["analytics_engine"].connect() as connection:
            connection.exec_driver_sql("SELECT 1 FROM request_events LIMIT 1")
        if not active:
            return {"status": "not_ready"}, 503
    except SQLAlchemyError:
        return {"status": "not_ready"}, 503
    return {"status": "ready", "version": current_app.config["APP_VERSION"]}


@web.route("/<locale>", methods=["GET"])
def home(locale):
    if locale in {"ukr", "eng"}:
        return redirect("/" + {"ukr": "uk", "eng": "en"}[locale], 301)
    if locale == "rus":
        abort(410)
    if locale not in LOCALES:
        abort(404)
    return page("calculator.html", locale)


def result_response(locale, source, legacy=False):
    dataset()
    form = {key: str(source.get(key, ""))[:200] for key in ("birth_date", "country", "sex")}
    errors = {}
    if legacy:
        original = source.get("country", "181")
        selected = repository().legacy_location(original, locale)
        form["country"] = selected["code"] if selected else ""
        form["sex"] = {"1": "total", "2": "female", "3": "male"}.get(source.get("sex", "1"), "")
    else:
        selected = repository().get_location(form["country"], locale) if form["country"] else None
    try:
        birth = validate_birth_date(form["birth_date"], today())
    except ValueError as exc:
        errors["birth_date"] = str(exc)
    for key in form:
        if len(source.getlist(key)) > 1:
            errors[key] = {"birth_date": "invalid_date", "country": "invalid_country", "sex": "invalid_sex"}[
                key
            ]
    if not selected:
        errors["country"] = "invalid_country"
    elif not selected["available"]:
        errors["country"] = "unavailable"
    if form["sex"] not in {"total", "female", "male"}:
        errors["sex"] = "invalid_sex"
    value = selected["values"].get(form["sex"]) if selected else None
    if selected and value is None and "sex" not in errors:
        errors["country"] = "unavailable"
    result = calculate(birth, value, today()) if not errors else None
    response = page(
        "calculator.html",
        locale,
        "result",
        "/result",
        noindex=True,
        selected=selected,
        form=form,
        errors=errors,
        result=result,
    )
    request.environ["lifetime.validity"] = "invalid" if errors else "valid"
    return response, 400 if errors else 200


@web.route("/<locale>/result", methods=["GET", "POST"])
def result(locale):
    if locale == "rus":
        abort(410)
    if locale in {"ukr", "eng"}:
        return result_response(
            {"ukr": "uk", "eng": "en"}[locale],
            request.args if request.method == "GET" else request.form,
            legacy=True,
        )
    if locale not in LOCALES:
        abort(404)
    if request.method == "GET":
        if request.args:
            # No redirects or reflection of personal query parameters.
            return page("calculator.html", locale, "result", "/result", noindex=True)
        return page("calculator.html", locale, "result", "/result", noindex=True)
    return result_response(locale, request.form)


@web.get("/<locale>/countries")
def countries(locale):
    if locale in {"ukr", "eng"}:
        return redirect("/" + {"ukr": "uk", "eng": "en"}[locale] + "/countries", 301)
    if locale == "rus":
        abort(410)
    if locale not in LOCALES:
        abort(404)
    dataset()
    query = request.args.get("q", "")[:100].strip()
    locations = repository().list_locations(locale)
    if query:
        locations = [
            loc
            for loc in locations
            if query.casefold() in loc["name"].casefold() or query.casefold() == loc["code"].casefold()
        ]
    return page(
        "countries.html",
        locale,
        "countries",
        "/countries",
        query=query,
        locations=locations,
        noindex=bool(query),
    )


@web.get("/<locale>/<slug>")
def location(locale, slug):
    if locale == "rus":
        abort(410)
    if locale in {"ukr", "eng"}:
        new_locale = {"ukr": "uk", "eng": "en"}[locale]
        dataset()
        old = repository().legacy_location(slug, new_locale)
        if not old:
            abort(404)
        return redirect(f"/{new_locale}/{old['slug']}", 301)
    if locale not in LOCALES:
        abort(404)
    if slug in {"methodology", "privacy"}:
        return page("content.html", locale, slug, f"/{slug}")
    dataset()
    selected = repository().get_location(slug, locale)
    if not selected:
        abort(404)
    if selected["slug"] != slug:
        return redirect(f"/{locale}/{selected['slug']}", 301)
    request.environ["lifetime.safe_path"] = f"/{locale}/{slug}"
    return page(
        "location.html", locale, "location", f"/{slug}", selected=selected, noindex=not selected["available"]
    )


@web.route("/rus/<path:rest>", methods=["GET", "POST"])
@web.route("/translations", methods=["GET", "POST"])
@web.route("/translations/<path:rest>", methods=["GET", "POST"])
def retired(rest=""):
    abort(410)


@web.get("/robots.txt")
def robots():
    origin = current_app.config["SERVICE_URL"]
    return (
        f"User-agent: *\nAllow: /\n\nSitemap: {origin}/sitemap.xml\n",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


@web.get("/sitemap.xml")
def sitemap():
    dataset()
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}urlset")
    origin = current_app.config["SERVICE_URL"]
    for locale in sorted(LOCALES):
        suffixes = ["", "/countries", "/methodology", "/privacy"]
        suffixes.extend("/" + loc["slug"] for loc in repository().list_locations(locale) if loc["available"])
        for suffix in suffixes:
            entry = ET.SubElement(root, "url")
            ET.SubElement(entry, "loc").text = f"{origin}/{locale}{suffix}"
            ET.SubElement(entry, "lastmod").text = current_app.config["CONTENT_UPDATED"]
    return (
        ET.tostring(root, encoding="utf-8", xml_declaration=True),
        200,
        {"Content-Type": "application/xml; charset=utf-8"},
    )
