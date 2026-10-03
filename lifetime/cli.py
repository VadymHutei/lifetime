"""Operator commands; analytics are never exposed as a public HTTP endpoint."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3

import click
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from lifetime.repositories.reference import ReferenceRepository


def output(value):
    click.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def register_cli(app):
    @app.cli.command("version")
    def version_command():
        click.echo(app.config["APP_VERSION"])

    @app.cli.command("migrate")
    def migrate():
        """Apply versioned reference and analytics schema migrations."""
        app.extensions["reference"].migrate()
        app.extensions["analytics"].migrate()
        click.echo("Reference and analytics migrations applied.")

    @app.cli.command("import-data")
    @click.option("--path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
    @click.option("--activate/--no-activate", default=True)
    def import_data(path, activate):
        """Validate and import a snapshot; activate it after successful staging."""
        repository = app.extensions["reference"]
        summary = repository.import_snapshot(path or app.config["SNAPSHOT_PATH"])
        if activate:
            repository.activate_dataset(summary.get("dataset_id") or summary["id"])
        output(summary)

    @app.cli.command("activate-data")
    @click.argument("dataset_id")
    def activate_data(dataset_id):
        """Activate a previously imported dataset, including a rollback revision."""
        app.extensions["reference"].activate_dataset(dataset_id)
        output(app.extensions["reference"].active_dataset())

    @app.cli.group("analytics")
    def analytics():
        """Private operator reports and maintenance."""

    @analytics.command("report")
    @click.option(
        "--group",
        type=click.Choice(["overview", "valid", "bots", "invalid", "suspicious", "normal", "daily"]),
        default="overview",
    )
    @click.option("--since", default=None)
    @click.option("--until", default=None)
    @click.option("--limit", type=click.IntRange(1, 10000), default=100)
    def report(group, since, until, limit):
        output(app.extensions["analytics"].report(group, since=since, until=until, limit=limit))

    @analytics.command("replay")
    def replay():
        output(app.extensions["analytics"].replay())

    @analytics.command("purge")
    def purge():
        output(app.extensions["analytics"].purge())

    @analytics.command("ingest-edge")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def ingest_edge(path):
        output(app.extensions["analytics"].ingest_edge(path))

    @app.cli.command("backup")
    @click.argument("destination", type=click.Path(path_type=Path))
    def backup(destination):
        """Create consistent SQLite backups, including committed WAL contents."""
        engines = [app.extensions[f"{name}_engine"] for name in ("reference", "analytics")]
        # Validate every source before creating any output, including mixed profiles.
        if any(engine.dialect.name != "sqlite" for engine in engines):
            raise click.ClickException(
                "flask backup supports SQLite only. Use the official mysqldump backup/restore "
                "workflow in docs/MYSQL.md for MySQL; no destination was created."
            )
        if any(not engine.url.database or engine.url.database == ":memory:" for engine in engines):
            raise click.ClickException("This backup command requires file-based SQLite databases")
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=False)
        for name in ("reference", "analytics"):
            engine = app.extensions[f"{name}_engine"]
            with closing(sqlite3.connect(engine.url.database)) as source:
                with closing(sqlite3.connect(destination / f"{name}.sqlite3")) as target:
                    source.backup(target)
        copied_engine = create_engine(URL.create("sqlite", database=str(destination / "reference.sqlite3")))
        try:
            active = ReferenceRepository(copied_engine).active_dataset()
        finally:
            copied_engine.dispose()
        (destination / "metadata.json").write_text(
            json.dumps(
                {"app_version": app.config["APP_VERSION"], "active_dataset": active}, default=str, indent=2
            ),
            encoding="utf-8",
        )
        click.echo(str(destination))
