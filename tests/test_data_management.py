"""Data management (issue #17): deleting and pruning crawls, projects, database info / migrate / vacuum."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import maintenance, storage
from rb_spider.core.crawl import crawl_site
from rb_spider.core.errors import InvalidArguments
from rb_spider.core.settings import CrawlSettings, Settings

from . import polygon


@pytest.fixture(scope="module")
def base_url():
    with polygon.serve() as url:
        yield url


@pytest.fixture
def engine():
    with storage.database() as engine:
        yield engine


def _crawl(engine, base_url: str, project: str, *, store_html: bool = False) -> int:
    settings = Settings(crawl=CrawlSettings(max_urls=5, store_html=store_html))
    return crawl_site(engine, f"{base_url}/", project, settings).crawl_id


def _invoke(*args: str, input: str | None = None) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["--json", *args], input=input)
    return result.exit_code, json.loads(result.stdout.strip().splitlines()[-1])  # a prompt may precede it


def _rows(engine, table: sa.Table, crawl_id: int) -> int:
    with engine.connect() as conn:
        return conn.execute(sa.select(sa.func.count()).where(table.c.crawl_id == crawl_id)).scalar_one()


def _age(engine, crawl_id: int, days: int) -> None:
    with engine.begin() as conn:
        started = datetime.now(UTC) - timedelta(days=days)
        conn.execute(sa.update(storage.crawls).where(storage.crawls.c.id == crawl_id).values(started_at=started))


def test_crawls_delete_dry_run_then_yes_removes_everything(base_url: str, engine) -> None:
    keep, gone = _crawl(engine, base_url, "site"), _crawl(engine, base_url, "site", store_html=True)
    assert storage.get_html(gone, f"{base_url}/") is not None

    code, data = _invoke("crawls", "delete", str(gone), "--dry-run")
    assert code == 0 and data["dry_run"] and [c["id"] for c in data["crawls"]] == [gone]
    assert _rows(engine, storage.pages, gone) > 0  # nothing deleted yet

    code, data = _invoke("crawls", "delete", str(gone), "--yes")
    assert code == 0 and not data["dry_run"] and data["pages"] == 5
    for table in (storage.pages, storage.links, storage.issues, storage.frontier):
        assert _rows(engine, table, gone) == 0
    assert storage.get_html(gone, f"{base_url}/") is None
    assert [r.id for r in storage.list_crawls(engine)] == [keep]


def test_delete_asks_and_can_be_declined(base_url: str, engine) -> None:
    crawl_id = _crawl(engine, base_url, "site")
    code, data = _invoke("crawls", "delete", str(crawl_id), input="n\n")
    assert code == 1 and data["error"]["code"] == "ABORTED"
    code, data = _invoke("--non-interactive", "crawls", "delete", str(crawl_id))
    assert code == 2 and "--yes" in data["error"]["message"]
    assert _rows(engine, storage.pages, crawl_id) == 5


def test_delete_unknown_or_running_crawl(base_url: str, engine) -> None:
    code, data = _invoke("crawls", "delete", "999", "--yes")
    assert code == 2 and data["error"]["code"] == "INVALID_ARGUMENTS"
    running, stale = _crawl(engine, base_url, "site"), _crawl(engine, base_url, "site")
    storage.set_pid(engine, running, os.getpid())  # status "running", its process alive
    with pytest.raises(InvalidArguments, match="still running"):
        maintenance.delete_crawls(engine, maintenance.select_crawls(engine, [running]))
    storage.set_pid(engine, stale, None)  # "running" without a process: left from an old spider, deletable
    assert maintenance.delete_crawls(engine, maintenance.select_crawls(engine, [stale])) == 5


def test_prune_keep_last_per_project_and_older_than(base_url: str, engine) -> None:
    a1, a2, a3 = (_crawl(engine, base_url, "a") for _ in range(3))
    b1 = _crawl(engine, base_url, "b")
    _age(engine, a1, 100)
    _age(engine, a2, 100)

    def pruned(**kwargs) -> list[int]:
        return sorted(r.id for r in maintenance.select_prune(engine, **kwargs))

    assert pruned(keep_last=1, older_than=None) == [a1, a2]
    assert pruned(keep_last=None, older_than=timedelta(days=90)) == [a1, a2]
    assert pruned(keep_last=2, older_than=timedelta(days=90)) == [a1]  # old AND beyond the last 2
    assert pruned(keep_last=0, older_than=None, project="b") == [b1]

    code, data = _invoke("crawls", "prune", "--keep-last", "1", "--yes")
    assert code == 0 and sorted(c["id"] for c in data["crawls"]) == [a1, a2]
    assert sorted(r.id for r in storage.list_crawls(engine)) == [a3, b1]


@pytest.mark.parametrize("args", [[], ["--older-than", "soon"], ["--keep-last", "1", "--project-name", "nope"]])
def test_prune_needs_a_valid_condition(args: list[str]) -> None:
    code, data = _invoke("crawls", "prune", *args)
    assert code == 2 and data["error"]["code"] == "INVALID_ARGUMENTS"


def test_parse_age() -> None:
    assert maintenance.parse_age("90d") == timedelta(days=90)
    assert maintenance.parse_age(" 12h ") == timedelta(hours=12)
    assert maintenance.parse_age("2w") == timedelta(weeks=2)


def test_projects_list_and_delete(base_url: str, engine) -> None:
    _crawl(engine, base_url, "shop")
    _crawl(engine, base_url, "shop")
    blog = _crawl(engine, base_url, "blog")

    code, data = _invoke("projects", "list")
    assert code == 0
    assert [(p["name"], p["crawls"], p["pages"]) for p in data["projects"]] == [("blog", 1, 5), ("shop", 2, 10)]

    code, data = _invoke("projects", "delete", "shop", "--dry-run")
    assert data == {"ok": True, "project": "shop", "crawls": 2, "pages": 10, "dry_run": True}
    code, data = _invoke("projects", "delete", "shop", "--yes")
    assert code == 0
    assert [p["name"] for p in maintenance.list_projects(engine)] == ["blog"]
    assert [r.id for r in storage.list_crawls(engine)] == [blog]
    assert _invoke("projects", "delete", "shop", "--yes")[0] == 2


def test_db_info_migrate_vacuum(base_url: str, engine) -> None:
    crawl_id = _crawl(engine, base_url, "site")
    code, info = _invoke("db", "info")
    assert code == 0
    assert info["crawls"] == 1 and info["pages"] == 5 and info["links"] > 0
    assert info["schema_revision"] == info["schema_head"] and info["pending_migrations"] == []

    code, data = _invoke("db", "migrate", "--dry-run")
    assert code == 0 and data["migrations"] == []

    _invoke("crawls", "delete", str(crawl_id), "--yes")
    code, data = _invoke("db", "vacuum")
    assert code == 0 and data["after_bytes"] <= data["before_bytes"]


def test_db_migrate_brings_an_old_schema_up(tmp_path) -> None:
    from alembic import command

    engine = storage.open_db(tmp_path / "old.sqlite")
    try:
        _, head, _ = maintenance._revisions(engine)
        config = storage.alembic_config()
        with engine.begin() as conn:  # an older spider's database: one revision behind
            config.attributes["connection"] = conn
            command.downgrade(config, "-1")
        info = maintenance.db_info(engine)
        assert info.schema_revision != head and info.pending_migrations == [head]
        assert maintenance.migrate(engine) == [head]
        assert maintenance.db_info(engine).pending_migrations == []
    finally:
        engine.dispose()


def test_url_id_migration_keeps_every_link(base_url: str, tmp_path) -> None:
    """0014 moves links to urls + link_rows; down and up again, the `links` view gives back the same rows
    (in the columns 0014 had: later migrations' columns are dropped on the way down)."""
    from alembic import command

    engine = storage.open_db(tmp_path / "links.sqlite")
    try:
        crawl_id = _crawl(engine, base_url, "site")
        columns = [c for c in storage.links.c if c.name not in ("fragment", "hreflang", "position", "path")]
        query = sa.select(*columns).where(storage.links.c.crawl_id == crawl_id)
        with engine.connect() as conn:
            before = sorted(tuple(row) for row in conn.execute(query))
        config = storage.alembic_config()
        for step in (lambda: command.downgrade(config, "0013"), lambda: command.upgrade(config, "head")):
            with engine.begin() as conn:
                config.attributes["connection"] = conn
                step()
        with engine.connect() as conn:
            after = sorted(tuple(row) for row in conn.execute(query))
        assert before and after == before
    finally:
        engine.dispose()
