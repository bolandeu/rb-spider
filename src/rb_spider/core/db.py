"""The tool's database: the shared PostgreSQL from `<TOOL>_DATABASE_URL`, else a local SQLite file.

- URL set → PostgreSQL only. Unreachable / wrong credentials → `DatabaseUnavailable`
  (exit 5). Never a silent fallback to SQLite: rows written there would be missing
  from the shared base without anyone noticing.
- URL not set → SQLite in the user data dir (tests, offline work).

Tables of kind "cache" live in PostgreSQL schema `cache` (tables.CACHE_SCHEMA), the data
in public. On SQLite the engine maps that schema away (`schema_translate_map`): one file,
as before. `upgrade` refuses up front when the schema is missing or this role can't
CREATE in it — before any migration runs, so nothing moves half-way.

Schema changes are Alembic migrations (`migrations/`), tracked in this tool's own
`alembic_version_<TOOL>` table. SQLite is brought up to date when opened. PostgreSQL
is never migrated implicitly — it's one database for every machine, and a dev
checkout must not migrate it: `<cli> db upgrade` does that, under an advisory lock;
opening it only checks the revision (behind → `DatabaseNotMigrated`, unknown → the
database is newer than this CLI, `DatabaseTooNew`).

spider's additions to the template: the old `SPIDER_DB_URL` still read (with a warning), the local file keeps its
name (`spider.sqlite`), a password missing from the URL comes from the keychain (`spider auth login --provider
database`), the SQL dialect bridge (`spider_casefold`, GLOB / instr on PostgreSQL), the old shared `alembic_version`
of a local file renamed once, and a new PostgreSQL starting from the frozen schema of 0033 (`migrations/pg_baseline.py`):
migrations 0001–0032 are SQLite's history only.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import platformdirs
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util import CommandError
from sqlalchemy import event
from sqlalchemy import exc as sa_exc

from .._distribution import TOOL
from .errors import CliError, DatabaseNotMigrated, DatabaseTooNew, DatabaseUnavailable, InvalidArguments
from .tables import CACHE_SCHEMA, PREFIX, metadata

_PACKAGE_NAME = __name__.split(".")[0]

ENV_VAR = f"{TOOL.upper()}_DATABASE_URL"
PATH_ENV_VAR = f"{TOOL.upper()}_DB_PATH"  # the local SQLite file elsewhere (a second database, an existing file)
LEGACY_ENV_VAR = f"{TOOL.upper()}_DB_URL"  # the name before 0.3; read while machines move to ENV_VAR
# What each one is for — `describe --json` lists them (x-rb-env).
ENV_VARS = {
    ENV_VAR: "Shared PostgreSQL URL; unset → the local SQLite file",
    PATH_ENV_VAR: "The local SQLite file, instead of the one in the user data dir",
    LEGACY_ENV_VAR: f"Deprecated name of {ENV_VAR}, still read",
}
VERSION_TABLE = f"alembic_version_{TOOL}"
CONNECT_TIMEOUT_S = 5
BASELINE = "0033"  # the revision a new PostgreSQL starts from (migrations/pg_baseline.py)
DB_CREDENTIAL = "database"  # `spider auth login --provider database`: the password of the database URL
MIN_SQLITE = (3, 44)  # string_agg()

_warned_legacy = False


def database_url() -> str | None:
    """`SPIDER_DATABASE_URL`, else the legacy `SPIDER_DB_URL` (a warning on stderr, once)."""
    global _warned_legacy
    if url := os.environ.get(ENV_VAR):
        return url
    if url := os.environ.get(LEGACY_ENV_VAR):
        if not _warned_legacy:
            _warned_legacy = True
            sys.stderr.write(f"warning: {LEGACY_ENV_VAR} is deprecated, rename it to {ENV_VAR}.\n")
        return url
    return None


def sqlite_path() -> Path:
    """The local database: `<TOOL>_DB_PATH`, else the app data dir (not Caches — cleaners wipe caches)."""
    if path := os.environ.get(PATH_ENV_VAR):
        return Path(path).expanduser()
    return platformdirs.user_data_path(TOOL, appauthor=False) / f"{TOOL}.sqlite"


def is_postgres(engine: sa.Engine | sa.Connection) -> bool:
    return engine.dialect.name == "postgresql"


def describe(engine: sa.Engine) -> str:
    """Where the engine points, password hidden — for doctor and `db status`."""
    return engine.url.render_as_string(hide_password=True)


def casefold(value: str | None) -> str | None:
    """`spider_casefold(x)` in SQLite: its lower() is ASCII-only, and rules compare Cyrillic text (anchors)."""
    return value.casefold() if value else value


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # readers (`spider status`) never block the writing crawl
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
    dbapi_connection.create_function("spider_casefold", 1, casefold, deterministic=True)


def check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise CliError(
            "SQLITE_TOO_OLD",
            f"SQLite {sqlite3.sqlite_version} is too old: spider needs {'.'.join(map(str, MIN_SQLITE))} or newer.",
            action="Install spider with a current Python: uv tool install --python 3.13 --reinstall rb-spider …",
        )


def sqlite_engine(path: Path) -> sa.Engine:
    check_sqlite_version()
    path.parent.mkdir(parents=True, exist_ok=True)
    # SQLite has no schemas: the cache tables sit in the same file as the data.
    engine = sa.create_engine(f"sqlite:///{path}", execution_options={"schema_translate_map": {CACHE_SCHEMA: None}})
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def postgres_url(url: str, *, env_var: str = ENV_VAR) -> sa.URL:
    """`url` for SQLAlchemy: the psycopg driver, and the keychain's password when the URL has none."""
    try:
        parsed = sa.make_url(url)
    except sa_exc.ArgumentError as exc:
        raise DatabaseUnavailable(f"{env_var} is not a database URL.") from exc
    if parsed.drivername.split("+")[0] not in ("postgres", "postgresql"):
        raise DatabaseUnavailable(f"{env_var}: only PostgreSQL is supported, not '{parsed.drivername}'.")
    if parsed.password is None and parsed.username:
        from ..providers import secrets

        if password := secrets.password(DB_CREDENTIAL):
            parsed = parsed.set(password=password)
    return parsed.set(drivername="postgresql+psycopg")


def postgres_engine(url: str, *, env_var: str = ENV_VAR) -> sa.Engine:
    """An engine for `url` (any `postgres://` / `postgresql://` spelling → the psycopg driver), connection checked."""
    parsed = postgres_url(url, env_var=env_var)
    engine = sa.create_engine(
        parsed,
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
    )
    event.listen(engine, "before_cursor_execute", _pg_statement, retval=True)
    try:
        with engine.connect():
            pass
    except sa_exc.OperationalError as exc:
        engine.dispose()
        where = parsed.render_as_string(hide_password=True)
        reason = str(exc.orig).strip().splitlines()[0]  # psycopg repeats it per address tried
        raise DatabaseUnavailable(f"Can't connect to {where}: {reason}") from exc
    return engine


# The rules, reports and exports are SQL written once for both dialects. The little SQLite has that PostgreSQL spells
# differently is rewritten on the way out, rather than emulated by functions in the shared `public` schema.
_GLOB = re.compile(r"\bGLOB '([^'*?]*)\*'")
_INSTR = re.compile(r"\binstr\(", re.IGNORECASE)


def _pg_statement(_conn, _cursor, statement: str, parameters, _context, _executemany):
    """SQLite's `x GLOB 'prefix*'` (case-sensitive, and it uses the index) is PostgreSQL's `x LIKE 'prefix%'`;
    `instr(a, b)` is `strpos(a, b)`."""
    if "GLOB" in statement:
        statement = _GLOB.sub(lambda m: "LIKE '" + m.group(1).replace("%", "%%").replace("_", "\\_") + "%%'", statement)
    if "instr(" in statement.lower():
        statement = _INSTR.sub("strpos(", statement)
    return statement, parameters


def alembic_config(connection: sa.Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", f"{_PACKAGE_NAME}:migrations")
    config.attributes.update(
        connection=connection,
        metadata=metadata_for(connection) if connection is not None else metadata,
        prefix=PREFIX,
        version_table=VERSION_TABLE,
        cache_schema=CACHE_SCHEMA,
    )
    return config


def metadata_for(bind: sa.Engine | sa.Connection) -> sa.MetaData:
    """tables.py as this database holds it: as declared on PostgreSQL; on SQLite without schemas."""
    if is_postgres(bind):
        return metadata
    flat = sa.MetaData(naming_convention=metadata.naming_convention)
    for table in metadata.sorted_tables:
        table.to_metadata(flat, schema=None)  # ty: ignore[invalid-argument-type] — None = no schema (SQLAlchemy docs)
    return flat


def _check_cache_schema(connection: sa.Connection) -> None:
    """PostgreSQL: schema `cache` exists and this role may use and CREATE in it — if any table needs it."""
    if not any(table.schema == CACHE_SCHEMA for table in metadata.sorted_tables):
        return
    exists = connection.execute(
        sa.text("SELECT 1 FROM pg_namespace WHERE nspname = :schema"), {"schema": CACHE_SCHEMA}
    ).scalar()
    action = (
        f"Schema '{CACHE_SCHEMA}' with USAGE and CREATE for this tool's role is set up by the infrastructure "
        "— ask the user (sysadmin sets it up); nothing was migrated."
    )
    if not exists:
        raise DatabaseUnavailable(
            f"The database has no schema '{CACHE_SCHEMA}' for this tool's cache tables.", action=action
        )
    missing = [
        privilege
        for privilege in ("USAGE", "CREATE")
        if not connection.execute(
            sa.text("SELECT has_schema_privilege(:schema, :privilege)"),
            {"schema": CACHE_SCHEMA, "privilege": privilege},
        ).scalar()
    ]
    if missing:
        raise DatabaseUnavailable(
            f"This database role lacks {' and '.join(missing)} on schema '{CACHE_SCHEMA}' (for the cache tables).",
            action=action,
        )


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("migrations/versions/ has no revisions")
    return head


def current_revision(connection: sa.Connection) -> str | None:
    return MigrationContext.configure(connection, opts={"version_table": VERSION_TABLE}).get_current_revision()


@dataclass(frozen=True)
class SchemaState:
    current: str | None
    head: str

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head

    @property
    def too_new(self) -> bool:
        """The database is at a revision this CLI's migrations don't contain: a newer release migrated it."""
        if self.current is None:
            return False
        try:
            return ScriptDirectory.from_config(alembic_config()).get_revision(self.current) is None
        except RevisionError, CommandError:  # alembic raises (not returns None) for an unknown id
            return True


def schema_state(engine: sa.Engine) -> SchemaState:
    _adopt_legacy_version_table(engine)
    with engine.connect() as connection:
        return SchemaState(current_revision(connection), head_revision())


def check_schema(engine: sa.Engine) -> None:
    """Raise unless the database is exactly at this CLI's head revision."""
    state = schema_state(engine)
    if state.up_to_date:
        return
    if state.too_new:
        raise DatabaseTooNew(state.current or "")
    raise DatabaseNotMigrated(state.current, state.head)


def upgrade(engine: sa.Engine) -> SchemaState:
    """Apply pending migrations, in one transaction. On PostgreSQL two runs at once queue on an advisory lock."""
    _adopt_legacy_version_table(engine)
    state = schema_state(engine)
    if state.up_to_date:
        return state
    if state.too_new:  # never "upgrade" a database to an older head
        raise DatabaseTooNew(state.current or "")
    with engine.begin() as connection:
        if is_postgres(connection):
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": VERSION_TABLE})
            _check_cache_schema(connection)
            if current_revision(connection) is None:  # a new database: the frozen schema of 0033, not SQLite's history
                from ..migrations import pg_baseline

                pg_baseline.create(connection)
                command.stamp(alembic_config(connection), BASELINE)
        command.upgrade(alembic_config(connection), "head")
    return schema_state(engine)


def _adopt_legacy_version_table(engine: sa.Engine) -> None:
    """A local file from before 0.3 keeps its revision in the shared-looking `alembic_version`: rename it once, before
    the revision is read (a migration can't move its own version table). Never on PostgreSQL — there another tool's
    `alembic_version` may live."""
    if is_postgres(engine):
        return
    with engine.begin() as connection:
        names = set(sa.inspect(connection).get_table_names())
        if "alembic_version" in names and VERSION_TABLE not in names:
            connection.exec_driver_sql(f"ALTER TABLE alembic_version RENAME TO {VERSION_TABLE}")


def open_db(*, check: bool = True) -> sa.Engine:
    """The database this CLI works with: `<TOOL>_DATABASE_URL`, else local SQLite.

    SQLite is migrated on open. PostgreSQL is only checked (`check=False` skips even
    that — for `db upgrade`/`db status` and doctor, which report the revision).
    """
    url = database_url()
    if url is None:
        engine = sqlite_engine(sqlite_path())
        upgrade(engine)
        return engine
    engine = postgres_engine(url)
    if check:
        check_schema(engine)
    return engine


@contextmanager
def connect() -> Iterator[sa.Connection]:
    """A transaction on the tool's database: committed on success, rolled back on error."""
    engine = open_db()
    try:
        with engine.begin() as connection:
            yield connection
    finally:
        engine.dispose()


def import_sqlite(source: Path, target: sa.Engine, *, dry_run: bool = False) -> dict[str, int]:
    """Copy this tool's tables from a local SQLite file into `target` (the shared database), in one transaction.

    The source is brought to the head revision first (its own migrations, like any
    open — even under `dry_run`), so both sides have the same tables. Every target table must be empty —
    an import is a one-off move, not a merge. Returns rows per table.
    """
    if not source.is_file():
        raise InvalidArguments(f"No SQLite database at '{source}'.")
    if target.url.database and Path(target.url.database).resolve() == source.resolve():
        raise InvalidArguments("Source and target are the same database.")
    source_engine = sqlite_engine(source)
    try:
        upgrade(source_engine)
        check_schema(target)
        counts: dict[str, int] = {}
        with source_engine.connect() as src, target.begin() as dst:
            for table in metadata.sorted_tables:  # parents before children (foreign keys)
                if dst.execute(sa.select(sa.func.count()).select_from(table)).scalar_one():
                    raise InvalidArguments(f"Table '{table.name}' in the target database is not empty.")
                counts[table.name] = src.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
                if dry_run:
                    continue
                rows = src.execute(sa.select(table)).mappings()
                while batch := rows.fetchmany(1000):
                    dst.execute(sa.insert(table), [dict(row) for row in batch])
                if is_postgres(dst):
                    _reset_sequences(dst, table)
        return counts
    finally:
        source_engine.dispose()


def _reset_sequences(connection: sa.Connection, table: sa.Table) -> None:
    """Rows came in with their ids: move each serial/identity sequence past them, or the next insert collides."""
    for column in table.primary_key.columns:
        if column.autoincrement is True or (column.autoincrement == "auto" and isinstance(column.type, sa.Integer)):
            top = f"SELECT max({column.name}) FROM {table.fullname}"  # noqa: S608 — names from tables.py, not input
            connection.execute(
                sa.text(f"SELECT setval(pg_get_serial_sequence(:table, :column), coalesce(({top}), 0) + 1, false)"),
                {"table": table.fullname, "column": column.name},
            )


def doctor_checks() -> list[dict]:
    """doctor's `database` and `database_schema` checks (connection, revision vs this CLI's head)."""
    legacy = []
    if not os.environ.get(ENV_VAR) and os.environ.get(LEGACY_ENV_VAR):
        legacy = [
            {"name": "database_env", "ok": True, "detail": f"{LEGACY_ENV_VAR} is deprecated: rename it to {ENV_VAR}"}
        ]
    try:
        engine = open_db(check=False)
    except DatabaseUnavailable as exc:
        return [*legacy, {"name": "database", "ok": False, "detail": exc.message}]
    try:
        state = schema_state(engine)
        checks = [{"name": "database", "ok": True, "detail": describe(engine)}]
        if state.up_to_date:
            checks.append({"name": "database_schema", "ok": True, "detail": state.head})
        else:
            problem = (
                DatabaseTooNew(state.current or "") if state.too_new else DatabaseNotMigrated(state.current, state.head)
            )
            checks.append({"name": "database_schema", "ok": False, "detail": f"{problem.message} {problem.action}"})
        return [*legacy, *checks]
    finally:
        engine.dispose()


__all__ = [
    "ENV_VAR",
    "LEGACY_ENV_VAR",
    "PATH_ENV_VAR",
    "PREFIX",
    "VERSION_TABLE",
    "SchemaState",
    "check_schema",
    "connect",
    "database_url",
    "doctor_checks",
    "import_sqlite",
    "metadata_for",
    "open_db",
    "schema_state",
    "sqlite_path",
    "upgrade",
]
