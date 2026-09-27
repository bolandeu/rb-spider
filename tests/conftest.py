from __future__ import annotations

import itertools
import os
from collections.abc import Generator, Iterator

import pytest

from rb_spider.core import settings

# SPIDER_TEST_PG=postgresql://user:password@host:port/db — run the suite against PostgreSQL (#41): every test gets a
# database of its own, cloned from a template that already has the schema. Without it the tests use SQLite files.
PG_ADMIN = os.environ.get("SPIDER_TEST_PG")
_PG_TEMPLATE = "spider_test_template"
_pg_names = itertools.count()


def _pg_admin():
    import sqlalchemy as sa

    assert PG_ADMIN
    return sa.create_engine(sa.make_url(PG_ADMIN).set(drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT")


def _pg_url(database: str) -> str:
    import sqlalchemy as sa

    assert PG_ADMIN
    return sa.make_url(PG_ADMIN).set(database=database).render_as_string(hide_password=False)


def db_env(engine=None) -> dict[str, str]:
    """Environment that points a CLI call at a database: `engine`'s (SQLite file or PostgreSQL), or the one the
    current environment points at — for a module fixture to hand its database to later tests."""
    if engine is None:
        return {"SPIDER_DB_PATH": os.environ["SPIDER_DB_PATH"], "SPIDER_DB_URL": os.environ.get("SPIDER_DB_URL", "")}
    if engine.dialect.name == "sqlite":
        return {"SPIDER_DB_PATH": str(engine.url.database), "SPIDER_DB_URL": ""}
    return {"SPIDER_DB_URL": engine.url.render_as_string(hide_password=False)}


def use_db(monkeypatch, engine=None, env: dict[str, str] | None = None) -> None:
    """Point this test's commands at a database (see db_env)."""
    for name, value in (env or db_env(engine)).items():
        monkeypatch.setenv(name, value)


@pytest.fixture(scope="session")
def _pg_template() -> Iterator[None]:
    from rb_spider.core import storage

    admin = _pg_admin()
    with admin.connect() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {_PG_TEMPLATE} WITH (FORCE)")
        conn.exec_driver_sql(f"CREATE DATABASE {_PG_TEMPLATE}")
    storage.open_db_url(_pg_url(_PG_TEMPLATE)).dispose()  # the schema, once
    yield
    with admin.connect() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {_PG_TEMPLATE} WITH (FORCE)")
    admin.dispose()


def _pg_database(prefix: str) -> Generator[str]:
    name = f"spider_test_{prefix}_{os.getpid()}_{next(_pg_names)}"
    admin = _pg_admin()
    with admin.connect() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE {name} TEMPLATE {_PG_TEMPLATE}")
    try:
        yield _pg_url(name)
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _isolated_session_db(tmp_path_factory, request) -> Iterator[None]:
    """Module-scoped fixtures (a shared polygon crawl) are set up before the per-test fixture below:
    without this they would write to the user's real crawl database."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SPIDER_DB_PATH", str(tmp_path_factory.mktemp("session-db") / "spider.sqlite"))
        patch.delenv("SPIDER_DB_URL", raising=False)
        if PG_ADMIN:
            request.getfixturevalue("_pg_template")
            databases = _pg_database("session")
            patch.setenv("SPIDER_DB_URL", next(databases))
            yield
            databases.close()
        else:
            yield


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path_factory, monkeypatch) -> Iterator[None]:
    """Every test gets its own crawl database and global config — never the user's real ones. With PostgreSQL the
    local path stays the session's: stored HTML is a file per database name there (storage.html_db_path)."""
    if not PG_ADMIN:
        monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path_factory.mktemp("db") / "spider.sqlite"))
    global_config = tmp_path_factory.mktemp("config") / "config.toml"
    monkeypatch.setattr(settings, "global_config_path", lambda: global_config)
    for name in list(os.environ):
        if name.startswith("SPIDER_") and "__" in name:  # settings env layer from the developer's shell
            monkeypatch.delenv(name)
    if PG_ADMIN:
        databases = _pg_database("t")
        monkeypatch.setenv("SPIDER_DB_URL", next(databases))
        yield
        databases.close()
    else:
        yield
