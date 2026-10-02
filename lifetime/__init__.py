"""LifeTime application factory. Schema creation and dataset import are CLI-only."""

from pathlib import Path
import os
import secrets

from flask import Flask, render_template, request
from werkzeug.exceptions import HTTPException

from lifetime.config import settings
from lifetime.database import make_engine
from lifetime.version import get_version


def create_app(config=None):
    from lifetime.analytics import AnalyticsStore, RequestAnalyticsMiddleware
    from lifetime.cli import register_cli
    from lifetime.repositories.reference import ReferenceRepository
    from lifetime.routes import web
    from lifetime.services.i18n import format_duration, format_number, translate

    app = Flask(__name__)
    app.config.update(settings(config))
    app.config["APP_VERSION"] = get_version()
    directory = Path(app.config["DATA_DIR"])
    directory.mkdir(parents=True, exist_ok=True)
    secret = app.config["ANALYTICS_SECRET"]
    if not secret:
        # A stable local-only key keeps pseudonymous addresses comparable after restart.
        key_file = directory / "analytics.key"
        if not key_file.exists():
            temporary = directory / (".analytics-key-" + secrets.token_hex(16))
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                    handle.write(secrets.token_hex(32))
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    # Publish a fully written key without replacing another worker's key.
                    os.link(temporary, key_file)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        secret = key_file.read_text(encoding="ascii").strip()
    reference_engine = make_engine(app.config["REFERENCE_DATABASE_URL"])
    analytics_engine = make_engine(app.config["ANALYTICS_DATABASE_URL"])
    app.extensions["reference_engine"] = reference_engine
    app.extensions["analytics_engine"] = analytics_engine
    app.extensions["reference"] = ReferenceRepository(reference_engine)
    store = AnalyticsStore(
        analytics_engine,
        directory / "spool",
        secret,
        app_version=app.config["APP_VERSION"],
        retain_days=app.config["ANALYTICS_RETENTION_DAYS"],
        raw_ip_days=app.config["ANALYTICS_RAW_IP_DAYS"],
        aggregate_days=app.config["ANALYTICS_AGGREGATE_DAYS"],
        store_raw_ip=app.config["ANALYTICS_STORE_RAW_IP"],
    )
    app.extensions["analytics"] = store
    app.register_blueprint(web)
    register_cli(app)

    @app.before_request
    def request_context():
        args = request.view_args or {}
        locale = args.get("locale", request.path.split("/")[1])
        if locale not in {"uk", "en"}:
            locale = "en" if locale == "eng" else "uk"
        request.environ["lifetime.locale"] = locale
        request.environ["lifetime.route"] = request.url_rule.rule if request.url_rule else None
        request.environ["lifetime.endpoint"] = request.endpoint

    @app.context_processor
    def shared_context():
        locale = request.environ.get("lifetime.locale", "uk")
        return {
            "version": app.config["APP_VERSION"],
            "t": lambda key: translate(key, locale),
            "number": lambda value, decimals=1: format_number(value, locale, decimals),
            "duration": lambda value, unit: format_duration(value, unit, locale),
            "default_url": app.config["SERVICE_URL"] + "/uk",
            "retention_days": app.config["ANALYTICS_RETENTION_DAYS"],
            "raw_ip_days": app.config["ANALYTICS_RAW_IP_DAYS"],
            "aggregate_days": app.config["ANALYTICS_AGGREGATE_DAYS"],
            "store_raw_ip": app.config["ANALYTICS_STORE_RAW_IP"],
        }

    @app.after_request
    def response_policy(response):
        path = request.path
        result_page = path.rstrip("/").endswith("/result")
        if response.status_code >= 400 or result_page or request.method == "POST":
            response.headers["X-Robots-Tag"] = "noindex, follow"
            response.headers["Cache-Control"] = "no-store"
        if response.status_code in {400, 404, 405, 410, 413, 415, 422}:
            request.environ["lifetime.validity"] = "invalid"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if app.config["ENVIRONMENT"] == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(Exception)
    def error(exc):
        status = exc.code if isinstance(exc, HTTPException) else 500
        if not isinstance(exc, HTTPException):
            # Avoid serializing exception details, query values or SQL parameters.
            app.logger.error("request_failed type=%s", type(exc).__name__)
        locale = request.environ.get("lifetime.locale", "uk")
        descriptions = {
            404: (
                "Сторінку не знайдено. Перевірте адресу або поверніться до калькулятора.",
                "This page was not found. Check the address or return to the calculator.",
            ),
            410: (
                "Ця сторінка більше не доступна. Скористайтеся українською або англійською версією.",
                "This page has been retired. Use the Ukrainian or English version.",
            ),
            503: (
                "Дані тимчасово недоступні. Спробуйте пізніше.",
                "Data is temporarily unavailable. Please try again later.",
            ),
            500: (
                "Не вдалося обробити запит. Спробуйте пізніше.",
                "We could not complete this request. Please try again later.",
            ),
        }
        message = descriptions.get(
            status, ("Перевірте параметри й повторіть запит.", "Check your input and try again.")
        )[locale == "en"]
        response = app.make_response(
            (
                render_template(
                    "error.html",
                    locale=locale,
                    status=status,
                    message=message,
                    page_title=f"{status} — LifeTime",
                    description=message,
                    noindex=True,
                    canonical=None,
                    alternates=[],
                    schema=[],
                    form={},
                ),
                status,
            )
        )
        if status == 405 and isinstance(exc, HTTPException):
            response.headers.extend(
                [(name, value) for name, value in exc.get_headers() if name.lower() == "allow"]
            )
        return response

    if app.config["ANALYTICS_ENABLED"]:
        app.wsgi_app = RequestAnalyticsMiddleware(
            app.wsgi_app,
            store,
            trusted_proxy_cidrs=app.config["TRUSTED_PROXY_CIDRS"],
            app_version=app.config["APP_VERSION"],
        )
    return app
