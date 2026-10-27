"""Shared fixtures: rerun a test file under the CI environment, and give each test its own local database."""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from collections.abc import Callable, Generator, Iterator

import pytest

from rb_spider.core import settings

# TEST_DATABASE_URL (set by scripts/pg_test.sh: a throwaway local server) — run the suite against PostgreSQL: every
# test gets a database of its own, cloned from a template that already has the schema. Without it: SQLite files.
PG_ADMIN = os.environ.get("TEST_DATABASE_URL")
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
        return {
            "SPIDER_DB_PATH": os.environ["SPIDER_DB_PATH"],
            "SPIDER_DATABASE_URL": os.environ.get("SPIDER_DATABASE_URL", ""),
        }
    if engine.dialect.name == "sqlite":
        return {"SPIDER_DB_PATH": str(engine.url.database), "SPIDER_DATABASE_URL": ""}
    return {"SPIDER_DATABASE_URL": engine.url.render_as_string(hide_password=False)}


def use_db(monkeypatch, engine=None, env: dict[str, str] | None = None) -> None:
    """Point this test's commands at a database (see db_env)."""
    for name, value in (env or db_env(engine)).items():
        monkeypatch.setenv(name, value)


def create_cache_schema(engine) -> None:
    """Schema `cache` for the cache tables: on production the infrastructure creates it, here the test does."""
    from rb_spider.core import tables

    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {tables.CACHE_SCHEMA}")


@pytest.fixture(scope="session")
def _pg_template() -> Iterator[None]:
    from rb_spider.core import db

    admin = _pg_admin()
    with admin.connect() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {_PG_TEMPLATE} WITH (FORCE)")
        conn.exec_driver_sql(f"CREATE DATABASE {_PG_TEMPLATE}")
    engine = db.postgres_engine(_pg_url(_PG_TEMPLATE))
    create_cache_schema(engine)
    db.upgrade(engine)  # the schema, once
    engine.dispose()
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
        patch.setenv("SPIDER_CACHE_DIR", str(tmp_path_factory.mktemp("session-cache")))
        patch.delenv("SPIDER_DATABASE_URL", raising=False)
        patch.delenv("SPIDER_DB_URL", raising=False)  # the legacy name, from the developer's shell
        if PG_ADMIN:
            request.getfixturevalue("_pg_template")
            databases = _pg_database("session")
            patch.setenv("SPIDER_DATABASE_URL", next(databases))
            yield
            databases.close()
        else:
            yield


_PUSH_LATER = None


@pytest.fixture(scope="session", autouse=True)
def _no_retry_pauses() -> Iterator[None]:
    """URLs that don't answer are asked again after crawl.retry_pause_s (5 s, 10 s): the polygon's dead-on-purpose
    traps would make every crawl wait. Retries still happen, without the wait; test_no_response_retries checks it."""
    global _PUSH_LATER
    from rb_spider.core.queue import MemoryQueue

    _PUSH_LATER = MemoryQueue.push_later
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(MemoryQueue, "push_later", lambda self, url, check, _delay: _PUSH_LATER(self, url, check, 0))
        yield


def real_retry_pauses(monkeypatch) -> None:
    """Undo _no_retry_pauses for one test."""
    from rb_spider.core.queue import MemoryQueue

    monkeypatch.setattr(MemoryQueue, "push_later", _PUSH_LATER)


# Typer reads these once, at import, and then forces terminal output — what a CI runner sets.
CI_ENV = {"GITHUB_ACTIONS": "true", "FORCE_COLOR": "1", "PY_COLORS": "1"}


@pytest.fixture
def same_in_ci(request: pytest.FixtureRequest) -> Callable[[str], None]:
    """Rerun this file's tests matching `-k` under CI_ENV in a fresh interpreter: the only way to set a value read at import."""
    if request.config.getoption("--snapshot-update"):
        pytest.skip("the snapshots are being written; there is nothing to compare yet")

    def run(selection: str) -> None:
        options = ["-k", selection, "-p", "no:cacheprovider", "--no-cov", "-q"]
        command = [sys.executable, "-m", "pytest", str(request.path), *options]
        env = {**os.environ, **CI_ENV}
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        assert result.returncode == 0, result.stdout[-3000:]

    return run


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path_factory, monkeypatch) -> Iterator[None]:
    """Every test gets its own crawl database, page storage and global config — never the user's real ones. With
    PostgreSQL the local path stays the session's: stored HTML is a file per database name there (storage.html_db_path)."""
    monkeypatch.setenv("SPIDER_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
    if not PG_ADMIN:
        monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path_factory.mktemp("db") / "spider.sqlite"))
    global_config = tmp_path_factory.mktemp("config") / "config.toml"
    monkeypatch.setattr(settings, "global_config_path", lambda: global_config)
    for name in list(os.environ):
        if name.startswith("SPIDER_") and "__" in name:  # settings env layer from the developer's shell
            monkeypatch.delenv(name)
    if PG_ADMIN:
        databases = _pg_database("t")
        monkeypatch.setenv("SPIDER_DATABASE_URL", next(databases))
        yield
        databases.close()
    else:
        yield
