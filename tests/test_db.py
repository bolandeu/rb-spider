"""The database contract (cli-generator architecture.md §12): names, version table, migrations, the shared PostgreSQL."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from typer.testing import CliRunner

from rb_spider.cli import app
from rb_spider.core import db, storage, tables
from rb_spider.core.errors import DatabaseNotMigrated, DatabaseTooNew, DatabaseUnavailable, InvalidArguments

from .conftest import PG_ADMIN

runner = CliRunner()
V1_VIEWS = {"spider_v1_crawls", "spider_v1_pages", "spider_v1_issues", "spider_v1_links"}


def invoke_json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.stdout)


def _add_crawl(engine: sa.Engine, project: str = "сайт") -> int:
    crawl_id = storage.start_crawl(engine, project, "https://example.com/")
    with engine.begin() as conn:
        conn.execute(sa.insert(tables.issues).values(crawl_id=crawl_id, code="x", url="https://example.com/"))
    return crawl_id


def _local(tmp_path: Path, name: str) -> sa.Engine:
    engine = db.sqlite_engine(tmp_path / name)
    db.upgrade(engine)
    return engine


def test_names_are_namespaced() -> None:
    assert all(table.name.startswith(db.PREFIX) for table in tables.metadata.sorted_tables)
    assert tables.links.name.startswith(db.PREFIX)
    assert db.VERSION_TABLE == "alembic_version_spider"
    assert (db.ENV_VAR, db.LEGACY_ENV_VAR) == ("SPIDER_DATABASE_URL", "SPIDER_DB_URL")


def test_sqlite_is_created_and_migrated_on_open(tmp_path: Path) -> None:
    engine = storage.open_db(tmp_path / "new.sqlite")
    inspector = sa.inspect(engine)
    names = inspector.get_table_names()
    assert db.VERSION_TABLE in names and "alembic_version" not in names
    assert {"spider_links", *V1_VIEWS} <= set(inspector.get_view_names())
    assert db.schema_state(engine).up_to_date
    engine.dispose()


def test_sqlite_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(db.PATH_ENV_VAR, str(tmp_path / "x.sqlite"))
    assert db.sqlite_path() == tmp_path / "x.sqlite"
    monkeypatch.delenv(db.PATH_ENV_VAR)
    assert db.sqlite_path().name == "spider.sqlite"  # the file every spider before 0.3 wrote


def test_old_version_table_is_adopted(tmp_path: Path) -> None:
    """A file from before 0.3 kept its revision in `alembic_version`: renamed once, then migrated as usual."""
    engine = _local(tmp_path, "old.sqlite")
    with engine.begin() as conn:
        conn.exec_driver_sql(f"ALTER TABLE {db.VERSION_TABLE} RENAME TO alembic_version")
    assert db.schema_state(engine).up_to_date
    assert "alembic_version" not in sa.inspect(engine).get_table_names()


def test_every_table_has_a_single_column_primary_key(tmp_path: Path) -> None:
    """Directus can't show or edit a table without one, and doesn't support a composite one: a surrogate `id` is the
    key, the natural key a UNIQUE constraint. Declared and migrated alike."""
    for table in tables.metadata.sorted_tables:
        assert [c.name for c in table.primary_key.columns] == ["id"], f"{table.name}: PRIMARY KEY must be `id`"
    inspector = sa.inspect(_local(tmp_path, "pk.sqlite"))
    for name in inspector.get_table_names():
        columns = inspector.get_pk_constraint(name)["constrained_columns"]
        assert len(columns) == 1, f"{name}: PRIMARY KEY must be one column, is {columns}"


def test_every_table_says_whether_it_is_data_or_cache() -> None:
    for table in tables.metadata.sorted_tables:
        assert table.info.get("kind") in ("data", "cache"), (
            f'{table.name}: info={{"kind": "data" | "cache"}} is required'
        )


def test_declared_views_exist_with_their_columns(tmp_path: Path) -> None:
    """Every view in tables.views is created by the migrations, with exactly the declared columns."""
    _assert_views_match(_local(tmp_path, "views.sqlite"))


def _assert_views_match(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing = set(inspector.get_view_names())
    assert tables.views.sorted_tables, "tables.views declares no view"
    for view in tables.views.sorted_tables:
        assert view.name.startswith(f"{db.PREFIX}v"), f"{view.name}: a view's name is spider_v<N>_<name>"
        assert view.name in existing, f"{view.name} is declared in tables.views but no migration creates it"
        columns = [column["name"] for column in inspector.get_columns(view.name)]
        assert columns == [column.name for column in view.columns], f"{view.name}: columns differ from tables.views"


def test_tables_match_the_migrations(tmp_path: Path) -> None:
    """tables.py and migrations/versions/ describe the same schema."""
    with _local(tmp_path, "schema.sqlite").connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_name": lambda name, type_, *_: type_ != "table" or name.startswith(db.PREFIX)}
        )
        assert compare_metadata(context, db.metadata_for(conn)) == []


def test_url_never_falls_back_to_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SPIDER_DB_PATH", str(tmp_path / "never.sqlite"))
    monkeypatch.setenv(db.ENV_VAR, "postgresql://user:secret@127.0.0.1:1/nowhere")
    code, payload = invoke_json("db", "info")
    assert code == 5
    assert payload["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "secret" not in payload["error"]["message"]
    assert not (tmp_path / "never.sqlite").exists()


@pytest.mark.parametrize("url", ["sqlite:///x.db", "not a url"])
def test_url_must_be_postgres(url: str) -> None:
    with pytest.raises(DatabaseUnavailable):
        db.postgres_engine(url)


def _as_postgres(monkeypatch: pytest.MonkeyPatch, engine: sa.Engine) -> None:
    """Route the URL branch to a SQLite engine: the shared-database rules without a server."""
    monkeypatch.setenv(db.ENV_VAR, "postgresql://stand-in")
    monkeypatch.setattr(db, "postgres_engine", lambda *_args, **_kwargs: engine)


def test_shared_database_is_never_migrated_implicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.sqlite")
    _as_postgres(monkeypatch, engine)
    with pytest.raises(DatabaseNotMigrated) as excinfo:
        storage.open_db()
    assert "db upgrade" in (excinfo.value.action or "")
    assert db.schema_state(engine).current is None  # untouched
    code, payload = invoke_json("crawls", "list")
    assert code == 1 and payload["error"]["code"] == "DATABASE_NOT_MIGRATED"


def test_db_upgrade_migrates_the_shared_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.sqlite")
    _as_postgres(monkeypatch, engine)
    code, payload = invoke_json("db", "upgrade", "--dry-run")
    assert code == 0 and payload["dry_run"] and payload["migrations"][-1] == payload["schema_head"]
    assert db.schema_state(engine).current is None

    code, payload = invoke_json("db", "upgrade")
    assert code == 0 and payload["migrations"][-1] == payload["schema_head"]
    storage.open_db()  # checked, fine now

    code, payload = invoke_json("db", "upgrade")
    assert payload["migrations"] == []
    code, payload = invoke_json("db", "migrate")  # the old name, kept for a release
    assert code == 0 and payload["migrations"] == []


def test_database_newer_than_the_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = _local(tmp_path, "shared.sqlite")
    with engine.begin() as conn:
        conn.execute(sa.text(f"UPDATE {db.VERSION_TABLE} SET version_num = 'from_the_future'"))  # noqa: S608
    _as_postgres(monkeypatch, engine)
    with pytest.raises(DatabaseTooNew):
        storage.open_db()
    with pytest.raises(DatabaseTooNew):
        db.upgrade(engine)  # never "upgrade" to an older head
    _code, payload = invoke_json("doctor")
    schema = next(check for check in payload["checks"] if check["name"] == "database_schema")
    assert schema["ok"] is False and "upgrade" in schema["detail"]


def test_doctor_reports_the_database_and_the_old_variable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _code, payload = invoke_json("doctor")
    checks = {check["name"]: check for check in payload["checks"]}
    assert checks["database"]["ok"] and checks["database_schema"]["ok"] and "database_env" not in checks
    _as_postgres(monkeypatch, _local(tmp_path, "shared.sqlite"))
    monkeypatch.delenv(db.ENV_VAR)
    monkeypatch.setenv(db.LEGACY_ENV_VAR, "postgresql://stand-in")
    _code, payload = invoke_json("doctor")
    checks = {check["name"]: check for check in payload["checks"]}
    assert db.ENV_VAR in checks["database_env"]["detail"] and checks["database_schema"]["ok"]


def test_import_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = _local(tmp_path, "old.sqlite")
    _add_crawl(source)
    _add_crawl(source, "второй")
    target = _local(tmp_path, "shared.sqlite")
    _as_postgres(monkeypatch, target)

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.sqlite"), "--dry-run")
    assert code == 0 and payload["rows"]["spider_crawls"] == 2 and payload["rows"]["spider_issues"] == 2
    with target.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(tables.crawls)).scalar_one() == 0

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.sqlite"))
    assert code == 0 and payload["rows"]["spider_projects"] == 2
    with target.connect() as conn:
        assert {row.name for row in conn.execute(sa.select(tables.projects))} == {"сайт", "второй"}

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.sqlite"))
    assert code == 2 and "not empty" in payload["error"]["message"]


def test_import_sqlite_rejects_bad_sources(tmp_path: Path) -> None:
    target = db.sqlite_engine(tmp_path / "shared.sqlite")
    with pytest.raises(InvalidArguments, match="No SQLite"):
        db.import_sqlite(tmp_path / "missing.sqlite", target)
    db.upgrade(target)
    with pytest.raises(InvalidArguments, match="same database"):
        db.import_sqlite(tmp_path / "shared.sqlite", target)


@pytest.mark.skipif(not PG_ADMIN, reason="TEST_DATABASE_URL not set (scripts/pg_test.sh)")
def test_postgres_from_scratch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A new shared database: nothing on open, the whole schema from `db upgrade`, only spider_* objects — no functions
    or aggregates of other names (an overloaded sum(boolean) would change every tool's queries), others' tables kept."""
    assert PG_ADMIN
    # It drops this tool's tables: never anything but a throwaway local server.
    assert sa.make_url(PG_ADMIN).host in ("127.0.0.1", "localhost"), "TEST_DATABASE_URL must be scripts/pg_test.sh's"
    from .conftest import _pg_admin, _pg_url

    name = f"spider_test_scratch_{os.getpid()}"
    admin = _pg_admin()
    with admin.connect() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.exec_driver_sql(f"CREATE DATABASE {name}")
    url = _pg_url(name)
    engine = db.postgres_engine(url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE directus_users (id int PRIMARY KEY)")  # someone else's table
        monkeypatch.setenv(db.ENV_VAR, url)
        with pytest.raises(DatabaseNotMigrated):
            storage.open_db()
        assert db.upgrade(engine).up_to_date
        _assert_views_match(engine)
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"include_name": lambda n, type_, *_: type_ != "table" or n.startswith(db.PREFIX)}
            )
            assert compare_metadata(context, tables.metadata) == []
            relations = (
                conn.exec_driver_sql(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'i', 'S')"
                )
                .scalars()
                .all()
            )
            functions = (
                conn.exec_driver_sql(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public'"
                )
                .scalars()
                .all()
            )
            assert set(relations) >= V1_VIEWS
        foreign = {r for r in relations if not r.startswith(("spider_", db.VERSION_TABLE, "directus_users"))}
        assert not foreign and set(functions) == {"spider_casefold"}

        crawl_id = _add_crawl(engine)
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT spider_casefold('ЁЖ')")).scalar_one() == "ёж"
            row = conn.execute(sa.text("SELECT project FROM spider_v1_crawls WHERE crawl_id = :c"), {"c": crawl_id})
            assert row.scalar_one() == "сайт"
            assert sa.inspect(conn).has_table("directus_users")
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.dispose()


@pytest.mark.skipif(not PG_ADMIN, reason="TEST_DATABASE_URL not set (scripts/pg_test.sh)")
def test_postgres_db_upgrade_command_from_scratch(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the root agent runs on production: `spider db upgrade [--dry-run]` on an empty database. SQLite's history
    (0001–0032) never runs there: the baseline of 0033 does, and the output says so."""
    assert PG_ADMIN and sa.make_url(PG_ADMIN).host in ("127.0.0.1", "localhost")
    from .conftest import _pg_admin, _pg_url

    name = f"spider_test_cli_{os.getpid()}"
    admin = _pg_admin()
    with admin.connect() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.exec_driver_sql(f"CREATE DATABASE {name}")
    monkeypatch.setenv(db.ENV_VAR, _pg_url(name))
    try:
        code, payload = invoke_json("db", "upgrade", "--dry-run")
        assert code == 0 and payload["dry_run"] and payload["migrations"] == [db.BASELINE, "0034", "0035"]
        code, payload = invoke_json("db", "upgrade")
        assert code == 0 and payload["migrations"] == [db.BASELINE, "0034", "0035"]
        engine = db.postgres_engine(_pg_url(name))
        try:
            names = set(sa.inspect(engine).get_table_names())
            assert "spider_pages" in names and "pages" not in names and "projects" not in names  # 0001 never ran
            assert db.schema_state(engine).up_to_date
        finally:
            engine.dispose()
        code, payload = invoke_json("db", "upgrade", "--dry-run")
        assert code == 0 and payload["migrations"] == []
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.dispose()


# --- kind="cache" tables live in PostgreSQL schema `cache` (template v1.6, T30); spider has none so far


def test_cache_tables_and_only_they_are_in_the_cache_schema() -> None:
    for table in tables.metadata.sorted_tables:
        expected = tables.CACHE_SCHEMA if table.info.get("kind") == "cache" else None
        assert table.schema == expected, f"{table.name}: kind={table.info.get('kind')} needs schema={expected!r}"
