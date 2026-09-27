"""PostgreSQL as the crawl database (#41). The whole suite runs against it with SPIDER_TEST_PG (scripts/check.sh --pg);
these are the parts that don't need a server: choosing and configuring the connection."""

from __future__ import annotations

import pytest

from rb_spider.core import maintenance, storage
from rb_spider.core.errors import RemoteDatabaseUnavailable

from .conftest import PG_ADMIN


def test_without_spider_db_url_the_database_is_the_sqlite_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SPIDER_DB_URL", raising=False)
    monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path / "x.sqlite"))
    with storage.database() as engine:
        assert engine.dialect.name == "sqlite" and (tmp_path / "x.sqlite").is_file()


def test_only_postgresql(monkeypatch) -> None:
    with pytest.raises(RemoteDatabaseUnavailable, match="only PostgreSQL"):
        storage.remote_url("mysql://u@h/db")
    with pytest.raises(RemoteDatabaseUnavailable, match="not a database URL"):
        storage.remote_url("not a url")


def test_password_comes_from_the_keychain_when_the_url_has_none(monkeypatch) -> None:
    from rb_spider.credentials import manager

    asked = []
    monkeypatch.setattr(manager, "get_secret", lambda provider, field="api_key": asked.append(provider) or "s3cret")
    url = storage.remote_url("postgresql://spider@db.example:5433/crawls")
    assert (url.drivername, url.password, url.port, url.database) == ("postgresql+psycopg", "s3cret", 5433, "crawls")
    assert asked == ["database"]
    inline = storage.remote_url("postgresql://spider:inline@db.example/crawls")
    assert inline.password == "inline"  # noqa: S105 — the URL's own password wins


def test_an_unreachable_server_is_a_clear_error() -> None:
    with pytest.raises(RemoteDatabaseUnavailable, match="Can't reach the database"):
        storage.open_db_url("postgresql://spider:x@127.0.0.1:1/none")


def test_glob_becomes_like_for_postgresql() -> None:
    statement, _ = storage._pg_statement(None, None, "SELECT 1 WHERE url GLOB 'https://*' AND x GLOB 'a_b*'", {}, None,
                                         False)  # fmt: skip
    assert statement == "SELECT 1 WHERE url LIKE 'https://%%' AND x LIKE 'a\\_b%%'"


def test_stored_html_is_a_local_file_per_remote_database(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path / "spider.sqlite"))
    monkeypatch.setenv("SPIDER_DB_URL", "postgresql://u@h/crawls")
    assert storage.html_db_path() == tmp_path / "spider-html-crawls.sqlite"


@pytest.mark.skipif(not PG_ADMIN, reason="needs SPIDER_TEST_PG")
def test_db_info_names_the_server() -> None:
    with storage.database() as engine:
        info = maintenance.db_info(engine)
    assert info.engine == "postgresql" and info.server_version and "***" in info.path
    assert info.schema_revision == info.schema_head and info.pending_migrations == []


def test_doctor_reports_an_unreachable_server(monkeypatch) -> None:
    import json

    from typer.testing import CliRunner

    from rb_spider.cli import app

    monkeypatch.setenv("SPIDER_DB_URL", "postgresql://spider:x@127.0.0.1:1/none")
    result = CliRunner().invoke(app, ["--json", "doctor"])
    [check] = [c for c in json.loads(result.stdout)["checks"] if c["name"] == "database"]
    assert not check["ok"] and "Can't reach" in check["detail"]
