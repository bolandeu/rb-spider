"""The crawl database: one SQLite file per user, holding every project and crawl.

Lives in the app data dir (not Caches — it's crawl history, and cleaners wipe caches), the way
the sibling `serp` tool keeps its journal; `SPIDER_DB_PATH` overrides it (tests, a second DB).
Schema changes go through Alembic migrations (`rb_spider/migrations`), applied automatically
when the database is opened. `metadata` below mirrors the latest migration.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import platformdirs
import sqlalchemy as sa
import zstandard
from alembic import command
from alembic.config import Config
from sqlalchemy import event

from .errors import InvalidArguments
from .extract import Page
from .scope import LINK_FIELDS
from .version import CLI_NAME

metadata = sa.MetaData()

projects = sa.Table(
    "projects",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String, nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
crawls = sa.Table(
    "crawls",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    sa.Column("start_url", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),  # running | finished | failed | interrupted
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
    sa.Column("settings", sa.JSON),  # resolved settings the crawl ran with: explains why two crawls differ
    sa.Column("pid", sa.Integer),  # process running the crawl (a detached one too) — to tell running from dead
)
pages = sa.Table(
    "pages",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("url", sa.String, primary_key=True),
    sa.Column("status_code", sa.Integer, nullable=False),
    sa.Column("redirect_url", sa.String),
    sa.Column("content_type", sa.String),
    sa.Column("title", sa.String),
    sa.Column("bytes", sa.Integer, nullable=False),
    sa.Column("depth", sa.Integer, nullable=False),
    sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("error", sa.String),  # why there is no response (status_code 0)
    sa.Column("blocked", sa.String),  # "robots_txt": not fetched on purpose (status_code 0)
    sa.Column("blocked_rule", sa.String),  # the robots.txt line that closed it: "Disallow: /private/"
    sa.Column("refresh_url", sa.String),  # target of a meta / HTTP Refresh
    sa.Column("refresh_kind", sa.String),  # "meta" | "http"
    # on-page elements (HTML pages only); the text is the first element, counts say how many there were
    sa.Column("title_count", sa.Integer),
    sa.Column("title_outside_head", sa.Integer),
    sa.Column("meta_description", sa.String),
    sa.Column("meta_description_count", sa.Integer),
    sa.Column("meta_description_outside_head", sa.Integer),
    sa.Column("meta_keywords", sa.String),  # the first <meta name="keywords">
    sa.Column("meta_keywords_count", sa.Integer),
    # computed after the crawl (issues.analyze): the title and description's width in Google's results, pixels
    sa.Column("title_px", sa.Integer),
    sa.Column("description_px", sa.Integer),
    sa.Column("h1", sa.String),
    sa.Column("h1_count", sa.Integer),
    sa.Column("h1_from_alt", sa.Boolean),  # the first h1's text comes from an image alt inside it
    sa.Column("h1_first_heading", sa.Boolean),  # the first heading on the page is the h1
    sa.Column("h2", sa.String),
    sa.Column("h2_count", sa.Integer),
    sa.Column("h2_sequential", sa.Boolean),  # the heading right before the first h2 is an h1
    # directives: meta robots + X-Robots-Tag, stored as ",noindex,nofollow," so rules can match ",name,"
    sa.Column("robots_directives", sa.String),
    sa.Column("robots_outside_head", sa.Integer),
    # canonical: <link rel=canonical> + `Link: <...>; rel="canonical"`; canonical_url is the first, absolute, no #fragment
    sa.Column("canonical_url", sa.String),
    sa.Column("canonical_count", sa.Integer),
    sa.Column("canonical_conflict", sa.Boolean),  # more than one distinct target
    sa.Column("canonical_outside_head", sa.Integer),
    sa.Column("canonical_invalid_attr", sa.Boolean),  # hreflang / lang / media / type on rel=canonical
    sa.Column("canonical_relative", sa.Boolean),
    sa.Column("canonical_fragment", sa.Boolean),
    # computed after the crawl (issues.analyze): can a search engine index this URL, and if not, why
    sa.Column("indexable", sa.Boolean),
    sa.Column("indexability_status", sa.String),
    # content: md5 of the HTML (exact duplicates), words of visible text, a "lorem ipsum" leftover
    sa.Column("content_md5", sa.String),
    sa.Column("word_count", sa.Integer),
    sa.Column("lorem_ipsum", sa.Boolean),
    # links: `external` — another site (checked, not crawled); `parsed` — the body was read (crawled, not
    # only checked); outlink counts are <a href> follow links, before any per-page limit
    sa.Column("external", sa.Boolean),
    sa.Column("parsed", sa.Boolean),
    sa.Column("internal_outlinks", sa.Integer),
    sa.Column("external_outlinks", sa.Integer),
    sa.Column("internal_nofollow_outlinks", sa.Integer),
    sa.Column("uncrawlable_outlinks", sa.Integer),
    # crawl.render: True — data from the rendered DOM; False — rendering failed, raw HTML used; NULL — not rendered
    sa.Column("rendered", sa.Boolean),
    # rendered pages: the server's HTML before JavaScript ran (JavaScript rules), links JS added (Link Origin),
    # console errors / warnings and resources robots.txt kept from the browser (rows: render_events)
    sa.Column("raw_title", sa.String),
    sa.Column("raw_meta_description", sa.String),
    sa.Column("raw_h1", sa.String),
    sa.Column("raw_canonical", sa.String),
    sa.Column("raw_directives", sa.String),
    sa.Column("raw_word_count", sa.Integer),
    sa.Column("js_outlinks", sa.Integer),
    sa.Column("js_errors", sa.Integer),
    sa.Column("js_warnings", sa.Integer),
    sa.Column("blocked_resources", sa.Integer),
    # the old AJAX crawling scheme: <meta name="fragment"> and <a href="…#!…"> links
    sa.Column("ajax_meta_fragment", sa.Boolean),
    sa.Column("hashbang_links", sa.Integer),
    # the response: time from sending the request to its headers, Last-Modified, all headers (JSON, lower-case names)
    sa.Column("response_ms", sa.Integer),
    sa.Column("last_modified", sa.String),
    sa.Column("headers", sa.String),
    # computed after the crawl (issues.analyze): <a href> links to the page from the site / pages linking to it /
    # distinct pages of the site it links to
    sa.Column("inlinks", sa.Integer),
    sa.Column("unique_inlinks", sa.Integer),
    sa.Column("unique_outlinks", sa.Integer),
    # bookmark targets (ids, <a name>) as 2-byte fingerprints, base64 (extract.anchor_ids); "" — none
    sa.Column("anchor_ids", sa.String),
    # computed after the crawl (issues.analyze): the URL checks the address fails, ",uppercase,parameters,"
    sa.Column("url_issues", sa.String),
    sa.Column("hreflang_outside_head", sa.Integer),  # <link rel=alternate hreflang> elements outside <head>
    sa.Column("pagination", sa.String),  # the page's own rel next/prev: "first" (next only) | "paginated" (has prev)
    # security: response headers missing or weak (",hsts,csp,xcto,xfo,referrer,"), what the body really is when
    # Content-Type says otherwise ("image → html"), forms, target=_blank links to other origins without noopener,
    # resources loaded protocol-relative (//host/...)
    sa.Column("security_missing", sa.String),
    sa.Column("sniffed_type", sa.String),
    sa.Column("forms", sa.Integer),
    sa.Column("unsafe_blank_links", sa.Integer),
    sa.Column("protocol_relative", sa.Integer),
    # HTML validation from the source (collect.html_validation; NULL — not checked): <head> / <body> tags, an element
    # before <html>, <head> not first in <html>, the first element in <head> that doesn't belong there
    sa.Column("head_tags", sa.Integer),
    sa.Column("body_tags", sa.Integer),
    sa.Column("body_before_html", sa.Boolean),
    sa.Column("head_not_first", sa.Boolean),
    sa.Column("invalid_head_element", sa.String),
    # mobile: <meta name="viewport"> content (NULL — none), Flash / Silverlight / Java plugins
    sa.Column("viewport", sa.String),
    sa.Column("plugins", sa.Integer),
    # content measures of the page's own text: Flesch Reading Ease, words per sentence, visible text as % of the
    # HTML, MinHash signature (collect.near_duplicates) for near duplicates
    sa.Column("flesch", sa.Float),
    sa.Column("words_per_sentence", sa.Float),
    sa.Column("text_ratio", sa.Float),
    sa.Column("minhash", sa.String),
    # structured data (collect.structured_data; NULL — not collected): formats found (",json-ld,"; "" — none),
    # types, counts of Schema.org validation errors / warnings, Google rich result errors / warnings, unparsable
    # blocks; the first messages ([severity, scope, type, property, text]) and each rich result feature's status
    sa.Column("sd_formats", sa.String),
    sa.Column("sd_types", sa.String),
    sa.Column("sd_parse_errors", sa.Integer),
    sa.Column("sd_errors", sa.Integer),
    sa.Column("sd_warnings", sa.Integer),
    sa.Column("sd_rich_errors", sa.Integer),
    sa.Column("sd_rich_warnings", sa.Integer),
    sa.Column("sd_messages", sa.String),
    sa.Column("sd_features", sa.String),
    sa.Index("pages_by_md5", "crawl_id", "content_md5"),
)
# Every URL handed to the crawl queue. `done` is set in the same transaction that stores the page,
# so after a crash (kill -9) the pending rows are exactly what still has to be fetched: resume
# rebuilds the in-memory queue from them, nothing is lost and nothing is fetched twice.
frontier = sa.Table(
    "frontier",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("url", sa.String, primary_key=True),
    sa.Column("depth", sa.Integer, nullable=False),
    sa.Column("check_only", sa.Boolean, nullable=False),  # status only, not read (other sites, resources)
    sa.Column("done", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Index("frontier_pending", "crawl_id", "done"),
)
# Every URL a crawl stored a link from or to, once: links refer to URLs by id. With ~33 links a page, two
# URL strings per link row (and two indexes over them) were most of the database and of the time spent
# writing it. Unique per crawl, url first: a lookup by URL needs no crawl_id to find its row.
urls = sa.Table(
    "urls",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.UniqueConstraint("url", "crawl_id", name="urls_by_url"),
)
LINK_DATA = (
    "kind", "internal", "anchor", "alt", "rel", "nofollow", "alt_attr", "sized", "fragment", "hreflang", "position",
    "path", "path_type", "origin",
)  # fmt: skip
link_rows = sa.Table(
    "link_rows",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("source_id", sa.Integer, nullable=False),  # urls.id
    sa.Column("target_id", sa.Integer, nullable=False),  # urls.id
    # hyperlink | canonical | redirect | refresh | hreflang | next | prev | form | mobile_alternate | image | css | js | media | iframe (resources the page loads)
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("internal", sa.Boolean, nullable=False),  # target is part of the site
    sa.Column("anchor", sa.String),
    sa.Column("alt", sa.String),  # alt of the image inside an image link
    sa.Column("rel", sa.String),
    sa.Column("nofollow", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("alt_attr", sa.Boolean),  # images: the alt attribute is present (even if empty)
    sa.Column("sized", sa.Boolean),  # images: width and height are set in the HTML
    sa.Column("fragment", sa.String),  # hyperlinks to a #bookmark: the id it should land on (Broken Bookmark)
    sa.Column("hreflang", sa.String),  # hreflang annotations: the language / region code, as written
    sa.Column(
        "position", sa.String
    ),  # hyperlinks: nav | header | footer | sidebar (custom.link_positions); NULL — content
    sa.Column("path", sa.String),  # hyperlinks: the landmark ancestors, /nav.menu/… (collect.link_path)
    sa.Column("path_type", sa.String),  # hyperlinks: a | p | r | l — the view spells them out (Path Type)
    # hyperlinks of a rendered page: b — in the server's HTML too, r — added by JavaScript; NULL — not rendered
    sa.Column("origin", sa.String),
    sa.Index("link_rows_by_source", "crawl_id", "source_id"),
    sa.Index("link_rows_by_target", "crawl_id", "target_id"),
    # links to a #bookmark are few: Broken Bookmark reads them without scanning every link of the crawl
    sa.Index("link_rows_with_fragment", "crawl_id", sqlite_where=sa.text("fragment IS NOT NULL")),
    # hreflang annotations: the Hreflang rules and report walk them both ways without scanning every link
    sa.Index("link_rows_hreflang_by_source", "crawl_id", "source_id", sqlite_where=sa.text("kind = 'hreflang'")),
    sa.Index("link_rows_hreflang_by_target", "crawl_id", "target_id", sqlite_where=sa.text("kind = 'hreflang'")),
    # rel next / prev: queries say `kind IN ('next', 'prev')` so SQLite can use it
    sa.Index("link_rows_pagination", "crawl_id", "source_id", sqlite_where=sa.text("kind IN ('next', 'prev')")),
    sa.Index("link_rows_mobile", "crawl_id", "source_id", sqlite_where=sa.text("kind = 'mobile_alternate'")),
)
# `links` is a view over link_rows with the URLs as text (migration 0014) — what rules, reports and
# `spider query` read. SQLite folds it into each query: a filter on `target` finds the id through `urls` first.
links = sa.Table(  # the view's columns, for reading it with SQLAlchemy (never written to)
    "links",
    sa.MetaData(),
    sa.Column("crawl_id", sa.Integer),
    sa.Column("source", sa.String),
    sa.Column("target", sa.String),
    sa.Column("kind", sa.String),
    sa.Column("internal", sa.Boolean),
    sa.Column("anchor", sa.String),
    sa.Column("alt", sa.String),
    sa.Column("rel", sa.String),
    sa.Column("nofollow", sa.Boolean),
    sa.Column("alt_attr", sa.Boolean),
    sa.Column("sized", sa.Boolean),
    sa.Column("fragment", sa.String),
    sa.Column("hreflang", sa.String),
    sa.Column("position", sa.String),
    sa.Column("path", sa.String),
    sa.Column("path_type", sa.String),
    sa.Column("origin", sa.String),  # html | rendered | html & rendered (Link Origin)
)
# Metrics enrichers (plugins, `core/enrich.py`) add to URLs: one row per URL, plugin and metric name.
url_metrics = sa.Table(
    "url_metrics",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("url", sa.String, primary_key=True),
    sa.Column("source", sa.String, primary_key=True),  # the enricher's entry point name
    sa.Column("name", sa.String, primary_key=True),
    sa.Column("value", sa.Float),
    sa.Column("text", sa.String),
)
# XML sitemaps a crawl read (sitemaps.crawl): every file, and every URL entry with the file it came from.
sitemap_files = sa.Table(
    "sitemap_files",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("kind", sa.String),  # urlset | sitemapindex; NULL — not fetched or not parsed (see error)
    sa.Column("bytes", sa.Integer),  # uncompressed: the protocol's limit is 50 MB
    sa.Column("urls", sa.Integer),
    sa.Column("sitemaps", sa.Integer),  # child sitemaps of an index
    sa.Column("error", sa.String),
)
sitemap_urls = sa.Table(
    "sitemap_urls",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("source", sa.String, nullable=False),  # the sitemap file
    sa.Column("lastmod", sa.String),
    sa.Index("sitemap_urls_by_url", "crawl_id", "url"),
)
# Custom Search and Custom Extraction results ([custom]): a search — the number of matches on a page (a row only
# when there are any); an extraction — each value, `n` its order on the page.
custom_values = sa.Table(
    "custom_values",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("kind", sa.String, nullable=False),  # search | extract
    sa.Column("name", sa.String, nullable=False),
    sa.Column("value", sa.String),
    sa.Column("n", sa.Integer, nullable=False),
    sa.Index("custom_values_by_name", "crawl_id", "kind", "name"),
)
# What the browser reported while rendering a page (crawl.render): console errors and warnings, uncaught exceptions,
# and resources it couldn't load — blocked by robots.txt, failed, or answered 4xx / 5xx. At most 50 of each per page.
render_events = sa.Table(
    "render_events",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("kind", sa.String, nullable=False),  # error | warning | blocked | failed
    sa.Column("message", sa.String),  # console text; for resources why: robots.txt, HTTP 404, failed: …
    sa.Column("resource", sa.String),  # blocked / failed: the resource's URL
    sa.Index("render_events_by_url", "crawl_id", "url"),
)
# Near-duplicate pairs (issues.analyze, from pages.minhash): each pair once, url_a < url_b.
near_duplicates = sa.Table(
    "near_duplicates",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url_a", sa.String, nullable=False),
    sa.Column("url_b", sa.String, nullable=False),
    sa.Column("similarity", sa.Float, nullable=False),  # estimated Jaccard similarity of the texts, 0–1
    sa.Index("near_duplicates_by_a", "crawl_id", "url_a"),
    sa.Index("near_duplicates_by_b", "crawl_id", "url_b"),
)
issues = sa.Table(
    "issues",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("code", sa.String, nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("detail", sa.String),
    sa.Index("issues_by_code", "crawl_id", "code"),
)


def db_path() -> Path:
    """`SPIDER_DB_PATH`, else `<app data dir>/spider/spider.sqlite` (~/Library/Application Support on macOS)."""
    explicit = os.environ.get(f"{CLI_NAME.upper()}_DB_PATH")
    if explicit:
        return Path(explicit)
    return Path(platformdirs.user_data_dir(CLI_NAME, appauthor=False)) / f"{CLI_NAME}.sqlite"


def html_db_path() -> Path:
    """Stored HTML (`crawl.store_html`) lives beside the crawl database, not in it: the main DB stays small."""
    main = db_path()
    return main.with_name(f"{main.stem}-html{main.suffix}")


html_metadata = sa.MetaData()
html_pages = sa.Table(
    "html",
    html_metadata,
    sa.Column("crawl_id", sa.Integer, primary_key=True),
    sa.Column("url", sa.String, primary_key=True),
    sa.Column("body", sa.LargeBinary, nullable=False),  # zstd-compressed response body
)


def _pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # readers (`spider status`) never block the writing crawl
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
    # SQLite's lower() is ASCII-only; rules compare Cyrillic text (anchors) case-insensitively
    dbapi_connection.create_function("casefold", 1, lambda s: s.casefold() if s else s, deterministic=True)


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "rb_spider:migrations")
    return config


def open_db(path: Path | None = None, *, migrate: bool = True) -> sa.Engine:
    """Open (creating if needed) the crawl database and bring its schema up to date.

    `migrate=False` leaves the schema as it is — for `spider db info|migrate`, which report it.
    """
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _pragmas)
    if migrate:
        config = alembic_config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    return engine


@contextmanager
def database(path: Path | None = None, *, migrate: bool = True) -> Iterator[sa.Engine]:
    """`open_db` for one command: the engine's connections are closed on exit."""
    engine = open_db(path, migrate=migrate)
    try:
        yield engine
    finally:
        engine.dispose()


def _now() -> datetime:
    return datetime.now(UTC)


def start_crawl(engine: sa.Engine, project: str, start_url: str, settings: dict | None = None) -> int:
    """Register a running crawl (creating the project on first use) and return its id."""
    with engine.begin() as conn:
        project_id = conn.execute(sa.select(projects.c.id).where(projects.c.name == project)).scalar()
        if project_id is None:
            insert_project = sa.insert(projects).values(name=project, created_at=_now()).returning(projects.c.id)
            project_id = conn.execute(insert_project).scalar_one()
        insert_crawl = (
            sa.insert(crawls)
            .values(project_id=project_id, start_url=start_url, status="running", started_at=_now(), settings=settings)
            .returning(crawls.c.id)
        )
        return conn.execute(insert_crawl).scalar_one()


def finish_crawl(engine: sa.Engine, crawl_id: int, status: str) -> int:
    """Close a crawl with its final status; returns the number of pages stored."""
    with engine.begin() as conn:
        count = conn.execute(sa.select(sa.func.count()).where(pages.c.crawl_id == crawl_id)).scalar_one()
        conn.execute(
            sa.update(crawls).where(crawls.c.id == crawl_id).values(status=status, finished_at=_now(), pages=count)
        )
        return count


_PAGE_COLUMNS = [column.name for column in pages.columns]
_LINK_COLUMNS = ["crawl_id", *LINK_FIELDS]


def _insert_json(table: sa.Table, columns: list[str], verb: str = "INSERT") -> str:
    """Insert rows passed as one JSON array of arrays (`json_each`): SQLite runs the whole batch in one
    step, without Python's GIL — `executemany` takes the GIL back after every row, and with the crawl's
    event loop busy on the same GIL that made writing three times slower."""
    values = ", ".join(f"json_extract(value, '$[{i}]')" for i in range(len(columns)))
    return f"{verb} INTO {table.name} ({', '.join(columns)}) SELECT {values} FROM json_each(?)"  # noqa: S608 — fixed names


_JSON_CHUNK = 5000  # rows per statement: a bounded JSON argument keeps SQLite's memory flat
_INSERT_PAGES = _insert_json(pages, _PAGE_COLUMNS, "INSERT OR REPLACE")  # a URL reached twice keeps its latest response
# A batch of links: its URLs get ids (new ones inserted), then the rows go in with the ids — all inside
# SQLite, so the writer keeps no URL -> id map in memory. Both statements read the same JSON chunk.
_LINK_JSON = ", ".join(f"json_extract(value, '$[{i}]') AS {name}" for i, name in enumerate(_LINK_COLUMNS))
_INSERT_LINK_URLS = (
    f"WITH r AS (SELECT {_LINK_JSON} FROM json_each(?)) "  # noqa: S608 — fixed names
    "INSERT OR IGNORE INTO urls (url, crawl_id) SELECT source, crawl_id FROM r UNION SELECT target, crawl_id FROM r"
)
# The ids by a lookup per row through the unique index — not a JOIN: with planner statistics from earlier, smaller
# crawls in the same database SQLite could pick a scan of `urls` per row (a 4-page crawl then a full one: 20 s).
_INSERT_LINK_ROWS = (
    f"WITH r AS (SELECT {_LINK_JSON} FROM json_each(?)) "  # noqa: S608 — fixed names
    f"INSERT INTO link_rows (crawl_id, source_id, target_id, {', '.join(LINK_DATA)}) "
    "SELECT r.crawl_id, (SELECT id FROM urls WHERE url = r.source AND crawl_id = r.crawl_id),"
    " (SELECT id FROM urls WHERE url = r.target AND crawl_id = r.crawl_id),"
    f" {', '.join(f'r.{c}' for c in LINK_DATA)} FROM r"
)
_INSERT_CUSTOM = _insert_json(custom_values, ["crawl_id", "url", "kind", "name", "value", "n"])
_INSERT_EVENTS = _insert_json(render_events, ["crawl_id", "url", "kind", "message", "resource"])
_INSERT_SITEMAP_URLS = _insert_json(sitemap_urls, ["crawl_id", "url", "source", "lastmod"])
_INSERT_QUEUED = _insert_json(frontier, ["crawl_id", "url", "depth", "check_only"], "INSERT OR IGNORE")
_MARK_DONE = "UPDATE frontier SET done = 1 WHERE crawl_id = ? AND url IN (SELECT value FROM json_each(?))"


def _timestamp() -> str:
    """`_now()` as SQLAlchemy stores a DateTime in SQLite — the writer bypasses SQLAlchemy's types."""
    return _now().strftime("%Y-%m-%d %H:%M:%S.%f")


@dataclass
class _Batch:
    custom: list[tuple] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)
    sitemap_files: list[dict] = field(default_factory=list)
    sitemap_urls: list[tuple] = field(default_factory=list)
    pages: list[tuple] = field(default_factory=list)
    links: list[tuple] = field(default_factory=list)
    queued: list[tuple] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    html: list[dict] = field(default_factory=list)


class PageWriter:
    """Buffers pages, links and queue entries and writes them in one transaction per batch.

    A batch goes out every `batch_size` pages or `flush_every_s` seconds, whichever comes first — memory
    stays flat however big the site is, and `spider status` sees progress while the crawl runs. One
    transaction for everything is what makes resume lossless (see `frontier`). With `store_html`,
    response bodies go zstd-compressed to the separate HTML database.

    Batches are written by a thread of their own (SQLite works without holding the GIL, so the crawl
    goes on meanwhile), one at a time: a new batch waits for the previous one, so a slow disk slows the
    crawl down instead of piling batches up in memory. Rows are plain tuples, sent to SQLite as JSON
    (`_insert_json`) — at ~80 links a page, SQLAlchemy's per-row work cost more than SQLite's.
    """

    def __init__(
        self,
        engine: sa.Engine,
        crawl_id: int,
        batch_size: int = 500,
        *,
        store_html: bool = False,
        flush_every_s: float = 2.0,
    ) -> None:
        self.engine, self.crawl_id, self.batch_size, self.flush_every_s = engine, crawl_id, batch_size, flush_every_s
        self._batch = _Batch()
        self._thread = ThreadPoolExecutor(1, thread_name_prefix="spider-writer")
        self._writing: Future | None = None
        self._last_flush = time.monotonic()
        self.count = 0  # pages handed to the writer so far, written or not
        self.html_engine: sa.Engine | None = None
        if store_html:
            path = html_db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.html_engine = sa.create_engine(f"sqlite:///{path}")
            html_metadata.create_all(self.html_engine)
            self._compressor = zstandard.ZstdCompressor(level=3)

    def queued(self, url: str, depth: int, check_only: bool) -> None:
        """A URL went into the crawl queue."""
        self._batch.queued.append((self.crawl_id, url, depth, check_only))

    def add(self, page: Page, depth: int, body: bytes | None = None) -> None:
        """A URL's result: stored with its queue entry marked done, in the same batch."""
        if self.html_engine is not None and body:
            self._batch.html.append(
                {"crawl_id": self.crawl_id, "url": page.url, "body": self._compressor.compress(body)}
            )
        # Every row carries every column: a batch insert needs one shape, and a redirect or an
        # error page has no on-page fields at all.
        row = page.onpage | {
            "crawl_id": self.crawl_id,
            "url": page.url,
            "status_code": page.status_code,
            "redirect_url": page.redirect_url,
            "content_type": page.content_type,
            "title": page.title,
            "bytes": page.bytes,
            "depth": depth,
            "fetched_at": _timestamp(),
            "error": page.error,
            "blocked": page.blocked,
            "refresh_url": page.refresh_url,
            "refresh_kind": page.refresh_kind,
        }
        self._batch.pages.append(tuple(row.get(column) for column in _PAGE_COLUMNS))
        self._batch.custom.extend((self.crawl_id, page.url, *values) for values in page.custom)
        self._batch.events.extend((self.crawl_id, page.url, *values) for values in page.events)
        self._batch.done.append(page.url)
        self.count += 1
        if len(self._batch.pages) >= self.batch_size or time.monotonic() - self._last_flush >= self.flush_every_s:
            self.flush(wait=False)

    def add_links(self, rows: list[tuple]) -> None:
        """`links` rows for this crawl, in `scope.LINK_FIELDS` order."""
        crawl_id = (self.crawl_id,)
        self._batch.links.extend(crawl_id + row for row in rows)

    def sitemap(self, file: dict, entries: list[tuple[str, str | None]]) -> None:
        """A sitemap file (sitemap_files columns) and its entries (url, lastmod), written with the next batch."""
        self._batch.sitemap_files.append({"crawl_id": self.crawl_id, **file})
        self._batch.sitemap_urls.extend((self.crawl_id, url, file["url"], lastmod) for url, lastmod in entries)

    def flush(self, *, wait: bool = True) -> None:
        """Hand the buffered rows to the writer thread; `wait` — return once everything is on disk."""
        self._last_flush = time.monotonic()
        batch, self._batch = self._batch, _Batch()
        self._wait()
        if batch.pages or batch.links or batch.queued or batch.html or batch.sitemap_files:
            self._writing = self._thread.submit(self._write, batch)
        if wait:
            self._wait()

    def close(self) -> None:
        """Write what's left and stop the writer thread."""
        try:
            self.flush()
        finally:
            self._thread.shutdown()
            if self.html_engine is not None:
                self.html_engine.dispose()

    def _wait(self) -> None:
        if self._writing is not None:
            writing, self._writing = self._writing, None
            writing.result()  # a failed write surfaces here, in the crawl

    def _write(self, batch: _Batch) -> None:
        if batch.html and self.html_engine is not None:  # a separate file: stored first, harmless if orphaned
            with self.html_engine.begin() as conn:
                conn.execute(sa.insert(html_pages).prefix_with("OR REPLACE"), batch.html)
        with self.engine.begin() as conn:
            for statements, rows in (
                ((_INSERT_QUEUED,), batch.queued),
                ((_INSERT_PAGES,), batch.pages),
                ((_INSERT_LINK_URLS, _INSERT_LINK_ROWS), batch.links),
            ):
                for chunk in range(0, len(rows), _JSON_CHUNK):  # SQLite parses a JSON argument whole
                    data = json.dumps(rows[chunk : chunk + _JSON_CHUNK], ensure_ascii=False)
                    for sql in statements:
                        conn.exec_driver_sql(sql, (data,))
            for rows, sql in ((batch.custom, _INSERT_CUSTOM), (batch.events, _INSERT_EVENTS)):
                for chunk in range(0, len(rows), _JSON_CHUNK):
                    conn.exec_driver_sql(sql, (json.dumps(rows[chunk : chunk + _JSON_CHUNK], ensure_ascii=False),))
            if batch.sitemap_files:
                conn.execute(sa.insert(sitemap_files), batch.sitemap_files)
            for chunk in range(0, len(batch.sitemap_urls), _JSON_CHUNK):
                data = json.dumps(batch.sitemap_urls[chunk : chunk + _JSON_CHUNK], ensure_ascii=False)
                conn.exec_driver_sql(_INSERT_SITEMAP_URLS, (data,))
            if batch.done:
                conn.exec_driver_sql(_MARK_DONE, (self.crawl_id, json.dumps(batch.done, ensure_ascii=False)))


def enqueue(engine: sa.Engine, crawl_id: int, urls: list[str], depth: int = 0) -> None:
    """Put URLs into a crawl's queue before it runs (list mode)."""
    rows = [(crawl_id, url, depth, False) for url in urls]
    with engine.begin() as conn:
        for chunk in range(0, len(rows), _JSON_CHUNK):
            conn.exec_driver_sql(_INSERT_QUEUED, (json.dumps(rows[chunk : chunk + _JSON_CHUNK], ensure_ascii=False),))


def reset_for_respider(engine: sa.Engine, crawl_id: int, targets: list[str]) -> list[str]:
    """Put a crawl's URLs back in its queue with their outgoing links and custom values removed (the page rows are
    replaced when fetched). Nothing changes if any URL isn't in the crawl — the unknown ones are returned."""
    with engine.begin() as conn:
        known = set(conn.execute(sa.select(frontier.c.url).where(frontier.c.crawl_id == crawl_id,
                                                                  frontier.c.url.in_(targets))).scalars())  # fmt: skip
        missing = [url for url in targets if url not in known]
        if missing:
            return missing
        ids = sa.select(urls.c.id).where(urls.c.crawl_id == crawl_id, urls.c.url.in_(targets))
        conn.execute(sa.delete(link_rows).where(link_rows.c.crawl_id == crawl_id, link_rows.c.source_id.in_(ids)))
        conn.execute(
            sa.delete(custom_values).where(custom_values.c.crawl_id == crawl_id, custom_values.c.url.in_(targets))
        )
        conn.execute(
            sa.delete(render_events).where(render_events.c.crawl_id == crawl_id, render_events.c.url.in_(targets))
        )
        conn.execute(sa.update(frontier).where(frontier.c.crawl_id == crawl_id, frontier.c.url.in_(targets))
                     .values(done=False))  # fmt: skip
    return []


def crawl_pid(engine: sa.Engine, crawl_id: int) -> int | None:
    with engine.connect() as conn:
        return conn.execute(sa.select(crawls.c.pid).where(crawls.c.id == crawl_id)).scalar()


def set_pid(engine: sa.Engine, crawl_id: int, pid: int | None) -> None:
    with engine.begin() as conn:
        conn.execute(sa.update(crawls).where(crawls.c.id == crawl_id).values(pid=pid, status="running"))


@dataclass
class Frontier:
    seen: dict[str, int]  # every queued URL -> depth
    pending: list[tuple[str, int, bool]]  # (url, depth, check_only) not done yet


def load_frontier(engine: sa.Engine, crawl_id: int) -> Frontier:
    """The queue a crawl left behind: what it has seen, and what it still has to fetch."""
    query = sa.select(frontier.c.url, frontier.c.depth, frontier.c.check_only, frontier.c.done).where(
        frontier.c.crawl_id == crawl_id
    )
    seen: dict[str, int] = {}
    pending: list[tuple[str, int, bool]] = []
    with engine.connect() as conn:
        for url, depth, check_only, done in conn.execute(query):
            seen[url] = depth
            if not done:
                pending.append((url, depth, check_only))
    return Frontier(seen, pending)


@dataclass
class Progress:
    pages: int  # stored so far
    pending: int  # queued, not fetched yet


def progress(engine: sa.Engine, crawl_id: int) -> Progress:
    with engine.connect() as conn:
        stored = conn.execute(sa.select(sa.func.count()).where(pages.c.crawl_id == crawl_id)).scalar_one()
        pending = conn.execute(
            sa.select(sa.func.count()).where(frontier.c.crawl_id == crawl_id, sa.not_(frontier.c.done))
        ).scalar_one()
    return Progress(stored, pending)


@dataclass
class CrawlRow:
    id: int
    project: str
    start_url: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages: int


def get_crawl(engine: sa.Engine, crawl_id: int) -> tuple[CrawlRow, dict | None]:
    """One crawl and the settings snapshot it ran with (None for crawls made before snapshots)."""
    query = (
        sa.select(
            crawls.c.id,
            projects.c.name,
            crawls.c.start_url,
            crawls.c.status,
            crawls.c.started_at,
            crawls.c.finished_at,
            crawls.c.pages,
            crawls.c.settings,
        )
        .join(projects, projects.c.id == crawls.c.project_id)
        .where(crawls.c.id == crawl_id)
    )
    with engine.connect() as conn:
        *fields, snapshot = conn.execute(query).one()
    row = CrawlRow(*fields)
    row.started_at = row.started_at.replace(tzinfo=UTC)
    row.finished_at = row.finished_at.replace(tzinfo=UTC) if row.finished_at else None
    return row, snapshot


def list_crawls(engine: sa.Engine, limit: int | None = None) -> list[CrawlRow]:
    """Crawls of every project, newest first."""
    query = (
        sa.select(
            crawls.c.id,
            projects.c.name,
            crawls.c.start_url,
            crawls.c.status,
            crawls.c.started_at,
            crawls.c.finished_at,
            crawls.c.pages,
        )
        .join(projects, projects.c.id == crawls.c.project_id)
        .order_by(crawls.c.id.desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        rows = [CrawlRow(*row) for row in conn.execute(query)]
    for row in rows:  # SQLite drops the timezone; everything is written in UTC
        row.started_at = row.started_at.replace(tzinfo=UTC)
        row.finished_at = row.finished_at.replace(tzinfo=UTC) if row.finished_at else None
    return rows


def get_html(crawl_id: int, url: str) -> bytes | None:
    """A stored response body (crawl made with `crawl.store_html`), or None."""
    path = html_db_path()
    if not path.is_file():
        return None
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as conn:
            where = sa.and_(html_pages.c.crawl_id == crawl_id, html_pages.c.url == url)
            blob = conn.execute(sa.select(html_pages.c.body).where(where)).scalar()
    finally:
        engine.dispose()
    return zstandard.ZstdDecompressor().decompress(blob) if blob is not None else None


def resolve_crawl_id(engine: sa.Engine, crawl_id: int | None) -> int:
    """The given crawl if it exists, else (None) the newest one — what analysis commands default to."""
    with engine.connect() as conn:
        if crawl_id is None:
            latest = conn.execute(sa.select(sa.func.max(crawls.c.id))).scalar()
            if latest is None:
                raise InvalidArguments(f"No crawls yet — run '{CLI_NAME} crawl <url>' first.")
            return latest
        if conn.execute(sa.select(crawls.c.id).where(crawls.c.id == crawl_id)).scalar() is None:
            raise InvalidArguments(f"No crawl #{crawl_id} — see '{CLI_NAME} crawls list'.")
        return crawl_id


def links_of(
    engine: sa.Engine, crawl_id: int, url: str, direction: str = "out", limit: int | None = None
) -> tuple[int, list[dict]]:
    """Links from (`out`) or to (`in`) a URL, with the response code of the URL at the other end."""
    mine, other = (links.c.source, links.c.target) if direction == "out" else (links.c.target, links.c.source)
    where = sa.and_(links.c.crawl_id == crawl_id, mine == url)
    query = (
        sa.select(
            links.c.source,
            links.c.target,
            links.c.kind,
            links.c.anchor,
            links.c.alt,
            links.c.rel,
            links.c.nofollow,
            links.c.internal,
            links.c.position,
            links.c.path,
            pages.c.status_code,
        )
        .select_from(links.outerjoin(pages, sa.and_(pages.c.crawl_id == links.c.crawl_id, pages.c.url == other)))
        .where(where)
        .order_by(other)
        .limit(limit)
    )
    with engine.connect() as conn:
        total = conn.execute(sa.select(sa.func.count()).select_from(links).where(where)).scalar_one()
        return total, [dict(row) for row in conn.execute(query).mappings()]
