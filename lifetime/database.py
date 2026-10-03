"""Small SQLAlchemy engine boundary; migrations are explicit CLI operations."""

from pathlib import Path
import ssl

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool


def make_engine(url, *, ssl_ca=None):
    url = make_url(url)
    kwargs = {"pool_pre_ping": True, "hide_parameters": True}
    if url.get_backend_name() == "mysql":
        if url.drivername != "mysql+pymysql":
            raise ValueError("MySQL requires the mysql+pymysql driver")
        connection_options = {
            "connect_timeout": 3,
            "read_timeout": 5,
            "write_timeout": 5,
            "charset": "utf8mb4",
            "local_infile": False,
        }
        if ssl_ca:
            connection_options["ssl"] = ssl.create_default_context(cafile=ssl_ca)
        kwargs.update(
            connect_args=connection_options,
            isolation_level="READ COMMITTED",
            pool_recycle=1800,
            pool_timeout=3,
            pool_size=5,
            max_overflow=5,
        )
    elif url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"timeout": 0.25, "check_same_thread": False}
        if url.database in {None, "", ":memory:"}:
            kwargs["poolclass"] = StaticPool
        else:
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    else:
        raise ValueError("Supported database backends are MySQL and SQLite")
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA busy_timeout=250")
            cursor.close()

    elif engine.dialect.name == "mysql":

        @event.listens_for(engine, "connect")
        def configure_mysql(connection, _record):
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout = 1")

    return engine
