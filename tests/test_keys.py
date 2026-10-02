"""Shared keys (T50): every page and URL carries `url_key` / `domain_key` from rb-keys — what the platform (Directus)
links competitors' and clients' pages by. Scenarios from tools (dev's order), 2026-10-02."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from rb_keys import norm_domain, norm_url
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import db, storage, tables
from rb_spider.core.crawl import crawl_site
from rb_spider.core.errors import DatabaseTooNew
from rb_spider.core.extract import Page
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon
from .conftest import PG_ADMIN

KEYED = (tables.pages, tables.urls)


@pytest.fixture
def engine():
    with storage.database() as engine:
        yield engine


def _link(source: str, target: str) -> tuple:
    """A `links` row in scope.LINK_FIELDS order."""
    return (source, target, "hyperlink", True, None, None, None, False, None, None, None, None, None, None, None, None)


def _write(engine: sa.Engine, pages: list[str], links: list[tuple[str, str]] = ()) -> int:
    crawl_id = storage.start_crawl(engine, "keys", "https://example.com/")
    writer = storage.PageWriter(engine, crawl_id)
    for url in pages:
        writer.add(Page(url=url, status_code=200, content_type="text/html", bytes=1), depth=0)
    writer.add_links([_link(source, target) for source, target in links])
    writer.close()
    return crawl_id


def _keys(engine: sa.Engine, table: sa.Table, crawl_id: int) -> dict[str, tuple[str | None, str | None]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(table.c.url, table.c.url_key, table.c.domain_key).where(table.c.crawl_id == crawl_id)
        )
        return {url: (url_key, domain_key) for url, url_key, domain_key in rows}


# --- 1. a stored page: url_key = keys url(url), domain_key = keys domain(url)


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


def test_crawled_pages_and_urls_carry_the_keys(base_url: str, engine: sa.Engine) -> None:
    """The home page links mailto: and javascript: too — the crawl finishes all the same."""
    result = crawl_site(engine, f"{base_url}/", "keys", Settings(crawl=CrawlSettings(max_urls=30)))
    with engine.connect() as conn:
        status = conn.execute(sa.select(tables.crawls.c.status).where(tables.crawls.c.id == result.crawl_id))
        assert status.scalar_one() == "finished"
    for table in KEYED:
        keys = _keys(engine, table, result.crawl_id)
        assert len(keys) > 1, table.name
        for url, found in keys.items():
            assert found == (norm_url(url), norm_domain(url)), f"{table.name}: {url}"


def test_written_page_has_its_keys(engine: sa.Engine) -> None:
    url = "https://www.Example.com/Catalog/?p=2#top"
    crawl_id = _write(engine, [url], [(url, "https://example.com/a")])
    assert _keys(engine, tables.pages, crawl_id) == {url: ("example.com/Catalog?p=2", "example.com")}
    assert _keys(engine, tables.urls, crawl_id) == {
        url: ("example.com/Catalog?p=2", "example.com"),
        "https://example.com/a": ("example.com/a", "example.com"),
    }


# --- 2. www, :443, utm_*, parameter order, the trailing / collapse into one url_key

VARIANTS = [
    "https://www.example.com/a/?b=2&a=1",
    "https://example.com:443/a?a=1&b=2",
    "https://example.com/a?b=2&utm_source=news&a=1&utm_medium=mail",
    "http://WWW.example.com/a/?a=1&b=2",
]


def test_variants_collapse_into_one_url_key(engine: sa.Engine) -> None:
    crawl_id = _write(engine, VARIANTS, [(VARIANTS[0], target) for target in VARIANTS[1:]])
    for table in KEYED:
        keys = _keys(engine, table, crawl_id)
        assert set(keys) == set(VARIANTS), table.name  # the URLs themselves stay as fetched
        assert set(keys.values()) == {("example.com/a?a=1&b=2", "example.com")}, table.name


# --- 3. mailto:, javascript:, a malformed URL (norm_url → ValueError) → NULL keys, not "", and nothing fails

UNKEYABLE = ["mailto:shop@example.com", "javascript:void(0)", "http://[::1", "https://example.com:abc/a"]


def test_unkeyable_urls_get_null_keys(engine: sa.Engine) -> None:
    good = "https://example.com/"
    crawl_id = _write(engine, [*UNKEYABLE, good], [(good, url) for url in UNKEYABLE])
    for table in KEYED:
        keys = _keys(engine, table, crawl_id)
        for url in UNKEYABLE:
            assert keys[url] == (None, None), f"{table.name}: {url}"
        assert keys[good] == ("example.com", "example.com")
    with engine.connect() as conn:
        for table in KEYED:
            empty = sa.select(sa.func.count()).where(sa.or_(table.c.url_key == "", table.c.domain_key == ""))
            assert conn.execute(empty).scalar_one() == 0


# --- 4. migration 0035 on an existing database: only ADD COLUMN + backfill, every row keyed

OLD_PAGES = ["https://www.example.com/a/?utm_source=x", "mailto:shop@example.com", "https://пример.рф/"]


def _fill_0034(conn: sa.Connection) -> int:
    """Rows as the previous release (schema 0034) wrote them: no key columns yet."""
    now = datetime(2026, 9, 1, tzinfo=UTC)
    project = conn.execute(
        sa.text("INSERT INTO spider_projects (name, created_at) VALUES ('старый', :now) RETURNING id"), {"now": now}
    ).scalar_one()
    crawl_id = conn.execute(
        sa.text(
            "INSERT INTO spider_crawls (project_id, start_url, status, started_at, pages)"
            " VALUES (:p, 'https://www.example.com/', 'finished', :now, 3) RETURNING id"
        ),
        {"p": project, "now": now},
    ).scalar_one()
    for url in OLD_PAGES:
        params = {"c": crawl_id, "url": url, "now": now}
        conn.execute(
            sa.text(
                "INSERT INTO spider_pages (crawl_id, url, status_code, bytes, depth, fetched_at)"
                " VALUES (:c, :url, 200, 1, 0, :now)"
            ),
            params,
        )
        conn.execute(sa.text("INSERT INTO spider_urls (crawl_id, url) VALUES (:c, :url)"), params)
    return crawl_id


def _assert_backfilled(engine: sa.Engine, crawl_id: int) -> None:
    expected = {
        OLD_PAGES[0]: ("example.com/a", "example.com"),
        OLD_PAGES[1]: (None, None),
        OLD_PAGES[2]: ("пример.рф", "пример.рф"),
    }
    for table in KEYED:
        assert _keys(engine, table, crawl_id) == expected, table.name
        indexed = [ix["column_names"] for ix in sa.inspect(engine).get_indexes(table.name)]
        assert ["url_key"] in indexed, f"{table.name}: no index on url_key"


def test_migration_0035_backfills_an_existing_sqlite_database(tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "old.sqlite")
    with engine.begin() as conn:
        command.upgrade(db.alembic_config(conn), "0034")
        crawl_id = _fill_0034(conn)
    assert db.upgrade(engine).up_to_date
    _assert_backfilled(engine, crawl_id)
    engine.dispose()


@pytest.fixture
def pg_scratch() -> str:
    assert PG_ADMIN and sa.make_url(PG_ADMIN).host in ("127.0.0.1", "localhost")
    from .conftest import _pg_admin, _pg_url

    name = f"spider_test_keys_{os.getpid()}"
    admin = _pg_admin()
    with admin.connect() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.exec_driver_sql(f"CREATE DATABASE {name}")
    try:
        yield _pg_url(name)
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.dispose()


@pytest.mark.skipif(not PG_ADMIN, reason="TEST_DATABASE_URL not set (scripts/pg_test.sh)")
def test_migration_0035_backfills_an_existing_postgres_database(pg_scratch: str, tmp_path: Path, monkeypatch) -> None:
    from rb_spider.migrations import pg_baseline

    engine = db.postgres_engine(pg_scratch)
    try:
        with engine.begin() as conn:
            pg_baseline.create(conn)
            command.stamp(db.alembic_config(conn), db.BASELINE)
            command.upgrade(db.alembic_config(conn), "0034")
            crawl_id = _fill_0034(conn)
        assert db.upgrade(engine).up_to_date
        _assert_backfilled(engine, crawl_id)
        with engine.connect() as conn:  # the views read the keys on PostgreSQL too
            row = conn.execute(
                sa.text("SELECT url_key, domain_key FROM spider_v1_pages WHERE url = :u"), {"u": OLD_PAGES[0]}
            ).one()
            assert tuple(row) == ("example.com/a", "example.com")

        monkeypatch.setenv(db.ENV_VAR, pg_scratch)  # 6. the previous release on the migrated base
        _old_cli(monkeypatch, tmp_path)
        with pytest.raises(DatabaseTooNew):
            storage.open_db()
    finally:
        engine.dispose()


# --- 5. the v1 views get url_key, domain_key — added at the end, nothing removed or renamed

V1_PAGES_0034 = [
    "id", "crawl_id", "url", "status_code", "redirect_url", "content_type", "indexable", "indexability_status",
    "title", "meta_description", "h1", "canonical_url", "robots_directives", "depth", "word_count", "response_ms",
    "inlinks", "unique_inlinks", "link_score", "fetched_at",
]  # fmt: skip
V1_LINKS_0034 = ["crawl_id", "source", "target", "kind", "internal", "anchor", "rel", "nofollow", "position", "origin"]


def test_v1_views_add_the_keys(engine: sa.Engine) -> None:
    for view, before in ((tables.v1_pages, V1_PAGES_0034), (tables.v1_links, V1_LINKS_0034)):
        declared = [column.name for column in view.columns]
        assert declared == [*before, "url_key", "domain_key"], view.name
        assert all(view.c[name].comment for name in ("url_key", "domain_key"))
        assert [c["name"] for c in sa.inspect(engine).get_columns(view.name)] == declared


def test_v1_views_read_the_keys(engine: sa.Engine) -> None:
    """spider_v1_links: the keys of the link's target — the URL it points to."""
    source, target = "https://www.example.com/", "https://example.com/a/?utm_source=x"
    crawl_id = _write(engine, [source], [(source, target)])
    with engine.connect() as conn:
        page = conn.execute(
            sa.text("SELECT url_key, domain_key FROM spider_v1_pages WHERE crawl_id = :c"), {"c": crawl_id}
        ).one()
        link = conn.execute(
            sa.text("SELECT target, url_key, domain_key FROM spider_v1_links WHERE crawl_id = :c"), {"c": crawl_id}
        ).one()
    assert tuple(page) == ("example.com", "example.com")
    assert tuple(link) == (target, "example.com/a", "example.com")


def test_describe_publishes_the_keys() -> None:
    result = CliRunner().invoke(app, ["describe", "--json"])
    meta = {item["name"]: item.get("value") for item in json.loads(result.stdout)["command"].get("metadata", [])}
    views = {view["name"]: view for view in meta["x-rb-data"]["views"]}
    for name in (tables.v1_pages.name, tables.v1_links.name):
        assert {"url_key", "domain_key"} <= {column["name"] for column in views[name]["columns"]}, name


# --- 6. the previous release on a migrated database → CLI_TOO_OLD, and it writes nothing


def _old_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make this CLI the previous release: its migrations stop at 0034."""
    source = Path(db.__file__).parent.parent / "migrations"
    old = tmp_path / "old_migrations"
    (old / "versions").mkdir(parents=True)
    for name in ("env.py", "script.py.mako"):
        shutil.copy(source / name, old / name)
    for path in (source / "versions").glob("*.py"):
        if path.name[:4].isdigit() and path.name[:4] <= "0034":
            shutil.copy(path, old / "versions" / path.name)
    new_config = db.alembic_config

    def old_config(connection=None):
        config = new_config(connection)
        config.set_main_option("script_location", str(old))
        return config

    monkeypatch.setattr(db, "alembic_config", old_config)


def test_old_cli_on_a_migrated_database_refuses_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = storage.open_db()  # migrated to head by this release
    with engine.connect() as conn:
        before = conn.execute(sa.select(sa.func.count()).select_from(tables.crawls)).scalar_one()
    _old_cli(monkeypatch, tmp_path)
    for argv in (["db", "upgrade"], ["crawl", "http://127.0.0.1:9/"]):
        result = CliRunner().invoke(app, [*argv, "--json"])
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert result.exit_code == 6 and payload["error"]["code"] == "CLI_TOO_OLD", argv
    with pytest.raises(DatabaseTooNew):
        storage.open_db()
    with engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(tables.crawls)).scalar_one() == before
        assert db.current_revision(conn) == "0035"  # not moved back
    engine.dispose()
