"""spider's tables, as SQLAlchemy Core — mirrors the latest migration (`migrations/versions/`).

Every name starts with `PREFIX` (`spider_`): the shared PostgreSQL holds every tool's tables (and Directus') in one
`public` schema. Change a table here *and* add a migration by hand — tests/test_db.py fails when the migrated schema
and this metadata disagree. Every table has a single-column PRIMARY KEY — Directus can't show or edit a table without
one and doesn't support a composite one: a surrogate `id` (in SQLite an alias of the rowid: free to write, and what
passes page by), with the natural key as a UNIQUE constraint.

Every table says what its rows are, `info={"kind": "data"}` or `"cache"` (tests/test_db.py fails without it): `data`
is the tool's result and lost when deleted; `cache` is a copy of something it can fetch again. `describe --json`
publishes it (x-rb-data).
"""

from __future__ import annotations

import sqlalchemy as sa

from .._distribution import TOOL

PREFIX = f"{TOOL}_"

# Deterministic constraint names: a later migration can drop or alter them by name on both PostgreSQL and SQLite
# (batch mode); they start with the (prefixed) table name.
metadata = sa.MetaData(
    naming_convention={
        "ix": "%(table_name)s_%(column_0_N_name)s_ix",
        "uq": "%(table_name)s_%(column_0_N_name)s_uq",
        "ck": "%(table_name)s_%(constraint_name)s_ck",
        "fk": "%(table_name)s_%(column_0_name)s_fk",
        "pk": "%(table_name)s_pk",
    }
)


# Row ids that grow with every crawl (URLs, links): bigint in PostgreSQL; in SQLite exactly INTEGER, the rowid alias
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _partial(where: str) -> dict:
    """A partial index's condition, in both dialects."""
    return {"sqlite_where": sa.text(where), "postgresql_where": sa.text(where)}


projects = sa.Table(
    "spider_projects",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String, nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    info={"kind": "data"},
)
crawls = sa.Table(
    "spider_crawls",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("project_id", sa.Integer, sa.ForeignKey("spider_projects.id", ondelete="CASCADE"), nullable=False),
    sa.Column("start_url", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),  # running | finished | failed | interrupted
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
    sa.Column("settings", sa.JSON),  # resolved settings the crawl ran with: explains why two crawls differ
    sa.Column("pid", sa.Integer),  # process running the crawl (a detached one too) — to tell running from dead
    info={"kind": "data"},
)
pages = sa.Table(
    "spider_pages",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
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
    # crawl.render_screenshots: the JPEG of the rendered page (a local file, storage.screenshots_dir)
    sa.Column("screenshot", sa.String),
    # `spider link-score`: internal PageRank on a 0–100 log scale (Link Score); NULL — not computed
    sa.Column("link_score", sa.Integer),
    # images: the real size, from the file's header (Image Details)
    sa.Column("image_width", sa.Integer),
    sa.Column("image_height", sa.Integer),
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
    sa.UniqueConstraint("crawl_id", "url", name="spider_pages_by_url"),  # a URL reached twice keeps its latest row
    sa.Index("spider_pages_by_md5", "crawl_id", "content_md5"),
    info={"kind": "data"},
)
# Every URL handed to the crawl queue. `done` is set in the same transaction that stores the page,
# so after a crash (kill -9) the pending rows are exactly what still has to be fetched: resume
# rebuilds the in-memory queue from them, nothing is lost and nothing is fetched twice.
frontier = sa.Table(
    "spider_frontier",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("depth", sa.Integer, nullable=False),
    sa.Column("check_only", sa.Boolean, nullable=False),  # status only, not read (other sites, resources)
    sa.Column("done", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.UniqueConstraint("crawl_id", "url", name="spider_frontier_by_url"),
    sa.Index("spider_frontier_pending", "crawl_id", "done"),
    info={"kind": "data"},
)
# Every URL a crawl stored a link from or to, once: links refer to URLs by id. With ~33 links a page, two
# URL strings per link row (and two indexes over them) were most of the database and of the time spent
# writing it. Unique per crawl, url first: a lookup by URL needs no crawl_id to find its row.
urls = sa.Table(
    "spider_urls",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.UniqueConstraint("url", "crawl_id", name="spider_urls_by_url"),
    info={"kind": "data"},
)
LINK_DATA = (
    "kind", "internal", "anchor", "alt", "rel", "nofollow", "alt_attr", "sized", "fragment", "hreflang", "position",
    "path", "path_type", "origin",
)  # fmt: skip
link_rows = sa.Table(
    "spider_link_rows",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("source_id", ID, nullable=False),  # urls.id
    sa.Column("target_id", ID, nullable=False),  # urls.id
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
    # hyperlinks of a rendered page: b — in the server's HTML too, r — added by JavaScript; NULL — not rendered.
    # images: c — a CSS background image
    sa.Column("origin", sa.String),
    sa.Index("spider_link_rows_by_source", "crawl_id", "source_id"),
    sa.Index("spider_link_rows_by_target", "crawl_id", "target_id"),
    # links to a #bookmark are few: Broken Bookmark reads them without scanning every link of the crawl
    sa.Index("spider_link_rows_with_fragment", "crawl_id", **_partial("fragment IS NOT NULL")),
    # hreflang annotations: the Hreflang rules and report walk them both ways without scanning every link
    sa.Index("spider_link_rows_hreflang_by_source", "crawl_id", "source_id", **_partial("kind = 'hreflang'")),
    sa.Index("spider_link_rows_hreflang_by_target", "crawl_id", "target_id", **_partial("kind = 'hreflang'")),
    # rel next / prev: queries say `kind IN ('next', 'prev')` so SQLite can use it
    sa.Index("spider_link_rows_pagination", "crawl_id", "source_id", **_partial("kind IN ('next', 'prev')")),
    sa.Index("spider_link_rows_mobile", "crawl_id", "source_id", **_partial("kind = 'mobile_alternate'")),
    info={"kind": "data"},
)
# `links` is a view over link_rows with the URLs as text (migration 0014) — what rules, reports and
# `spider query` read. SQLite folds it into each query: a filter on `target` finds the id through `urls` first.
links = sa.Table(  # the view's columns, for reading it with SQLAlchemy (never written to)
    "spider_links",
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
    sa.Column(
        "origin", sa.String
    ),  # hyperlinks: html | rendered | html & rendered (Link Origin); images: css background
)
# Metrics enrichers (plugins, `core/enrich.py`) add to URLs: one row per URL, plugin and metric name.
url_metrics = sa.Table(
    "spider_url_metrics",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("source", sa.String, nullable=False),  # the enricher's entry point name
    sa.Column("name", sa.String, nullable=False),
    sa.Column("value", sa.Float),
    sa.Column("text", sa.String),
    sa.UniqueConstraint("crawl_id", "url", "source", "name", name="spider_url_metrics_key"),
    info={"kind": "data"},
)
# XML sitemaps a crawl read (sitemaps.crawl): every file, and every URL entry with the file it came from.
sitemap_files = sa.Table(
    "spider_sitemap_files",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("kind", sa.String),  # urlset | sitemapindex; NULL — not fetched or not parsed (see error)
    sa.Column("bytes", sa.Integer),  # uncompressed: the protocol's limit is 50 MB
    sa.Column("urls", sa.Integer),
    sa.Column("sitemaps", sa.Integer),  # child sitemaps of an index
    sa.Column("error", sa.String),
    info={"kind": "data"},
)
sitemap_urls = sa.Table(
    "spider_sitemap_urls",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("source", sa.String, nullable=False),  # the sitemap file
    sa.Column("lastmod", sa.String),
    sa.Index("spider_sitemap_urls_by_url", "crawl_id", "url"),
    info={"kind": "data"},
)
# Custom Search and Custom Extraction results ([custom]): a search — the number of matches on a page (a row only
# when there are any); an extraction — each value, `n` its order on the page.
custom_values = sa.Table(
    "spider_custom_values",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("kind", sa.String, nullable=False),  # search | extract
    sa.Column("name", sa.String, nullable=False),
    sa.Column("value", sa.String),
    sa.Column("n", sa.Integer, nullable=False),
    sa.Index("spider_custom_values_by_name", "crawl_id", "kind", "name"),
    info={"kind": "data"},
)
# What the browser reported while rendering a page (crawl.render): console errors and warnings, uncaught exceptions,
# and resources it couldn't load — blocked by robots.txt, failed, or answered 4xx / 5xx. At most 50 of each per page.
render_events = sa.Table(
    "spider_render_events",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("kind", sa.String, nullable=False),  # error | warning | blocked | failed
    sa.Column("message", sa.String),  # console text; for resources why: robots.txt, HTTP 404, failed: …
    sa.Column("resource", sa.String),  # blocked / failed: the resource's URL
    sa.Index("spider_render_events_by_url", "crawl_id", "url"),
    info={"kind": "data"},
)
# `spider lighthouse`: every audit of every page Lighthouse measured (and spider's own mobile measures, `spider-*`),
# per strategy. Items — up to 20 of the audit's resources as JSON (URL, wasted bytes / ms), for the reports. From
# PageSpeed Insights also the CrUX field data: `crux:<metric>` / `crux-origin:<metric>` (score 1 / 0.5 / 0 — FAST /
# AVERAGE / SLOW; value — the 75th percentile, ms or CLS).
lighthouse_audits = sa.Table(
    "spider_lighthouse_audits",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("strategy", sa.String, nullable=False),  # mobile | desktop
    sa.Column("audit", sa.String, nullable=False),  # Lighthouse's audit id; category:<name> — a category's score
    sa.Column("score", sa.Float),  # 0–1; NULL — informative / not applicable
    sa.Column("value", sa.Float),  # numericValue (ms, bytes, CLS…)
    sa.Column("display", sa.String),  # displayValue as Lighthouse words it
    sa.Column("items", sa.String),
    sa.Column("source", sa.String),  # local | psi; NULL — measured before 0032 (local)
    sa.Index("spider_lighthouse_audits_by_url", "crawl_id", "url"),
    info={"kind": "data"},
)
# Images as a rendered page laid them out (crawl.render_images): real size against the size shown (Incorrectly Sized
# Images, Image Details). At most 200 per page.
rendered_images = sa.Table(
    "spider_rendered_images",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url", sa.String, nullable=False),  # the page
    sa.Column("image", sa.String, nullable=False),
    sa.Column("real_width", sa.Integer),
    sa.Column("real_height", sa.Integer),
    sa.Column("display_width", sa.Integer),
    sa.Column("display_height", sa.Integer),
    sa.Index("spider_rendered_images_by_url", "crawl_id", "url"),
    info={"kind": "data"},
)
# Near-duplicate pairs (issues.analyze, from pages.minhash): each pair once, url_a < url_b.
near_duplicates = sa.Table(
    "spider_near_duplicates",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("url_a", sa.String, nullable=False),
    sa.Column("url_b", sa.String, nullable=False),
    sa.Column("similarity", sa.Float, nullable=False),  # estimated Jaccard similarity of the texts, 0–1
    sa.Index("spider_near_duplicates_by_a", "crawl_id", "url_a"),
    sa.Index("spider_near_duplicates_by_b", "crawl_id", "url_b"),
    info={"kind": "data"},
)
issues = sa.Table(
    "spider_issues",
    metadata,
    sa.Column("id", ID, primary_key=True),
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("spider_crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("code", sa.String, nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("detail", sa.String),
    sa.Index("spider_issues_by_code", "crawl_id", "code"),
    info={"kind": "data"},
)

# The `spider_v1_*` views other tools, Directus and the platform read instead of the tables (migration 0034) — the
# tool's data contract, published by `describe --json` (x-rb-data.views). tests/test_db.py fails when a view below is
# missing from the migrated database or its columns differ. Columns never change: a different shape is a new `_v2_`
# view next to the old one. Kept out of `metadata`, which mirrors the tables only.
views = sa.MetaData()

v1_crawls = sa.Table(
    f"{PREFIX}v1_crawls",
    views,
    sa.Column("crawl_id", sa.Integer, comment="Crawl id"),
    sa.Column("project", sa.String, comment="Project name"),
    sa.Column("start_url", sa.String, comment="The URL the crawl started from"),
    sa.Column("status", sa.String, comment="running | finished | failed | interrupted"),
    sa.Column("started_at", sa.DateTime(timezone=True), comment="When the crawl started"),
    sa.Column("finished_at", sa.DateTime(timezone=True), comment="When it ended; NULL while running"),
    sa.Column("pages", sa.Integer, comment="URLs stored"),
    comment="One row per crawl",
)
v1_pages = sa.Table(
    f"{PREFIX}v1_pages",
    views,
    sa.Column("id", ID, comment="Page row id"),
    sa.Column("crawl_id", sa.Integer, comment="Crawl id (spider_v1_crawls)"),
    sa.Column("url", sa.String, comment="The URL"),
    sa.Column("status_code", sa.Integer, comment="HTTP status; 0 — no response or blocked by robots.txt"),
    sa.Column("redirect_url", sa.String, comment="Location of a redirect"),
    sa.Column("content_type", sa.String, comment="Content-Type"),
    sa.Column("indexable", sa.Boolean, comment="Can a search engine index the URL"),
    sa.Column("indexability_status", sa.String, comment="Why not: noindex, canonicalised, redirect, …"),
    sa.Column("title", sa.String, comment="The first <title>"),
    sa.Column("meta_description", sa.String, comment="The first meta description"),
    sa.Column("h1", sa.String, comment="The first h1"),
    sa.Column("canonical_url", sa.String, comment="The canonical URL, absolute"),
    sa.Column("robots_directives", sa.String, comment="meta robots + X-Robots-Tag as ',noindex,nofollow,'"),
    sa.Column("depth", sa.Integer, comment="Clicks from the start URL"),
    sa.Column("word_count", sa.Integer, comment="Words of visible text"),
    sa.Column("response_ms", sa.Integer, comment="Time to the response headers, ms"),
    sa.Column("inlinks", sa.Integer, comment="<a href> links to the page from the site"),
    sa.Column("unique_inlinks", sa.Integer, comment="Distinct pages linking to it"),
    sa.Column("link_score", sa.Integer, comment="Internal PageRank, 0–100; NULL — not computed"),
    sa.Column("fetched_at", sa.DateTime(timezone=True), comment="When it was fetched"),
    comment="One row per URL of a crawl: response and on-page SEO data",
)
v1_issues = sa.Table(
    f"{PREFIX}v1_issues",
    views,
    sa.Column("id", ID, comment="Issue row id"),
    sa.Column("crawl_id", sa.Integer, comment="Crawl id (spider_v1_crawls)"),
    sa.Column("code", sa.String, comment="Check code (`spider issues`)"),
    sa.Column("url", sa.String, comment="The URL the check found"),
    sa.Column("detail", sa.String, comment="What exactly, when the check says"),
    comment="One row per issue a check found on a URL",
)
v1_links = sa.Table(
    f"{PREFIX}v1_links",
    views,
    sa.Column("crawl_id", sa.Integer, comment="Crawl id (spider_v1_crawls)"),
    sa.Column("source", sa.String, comment="The page the link is on"),
    sa.Column("target", sa.String, comment="Where it points"),
    sa.Column("kind", sa.String, comment="hyperlink | canonical | redirect | hreflang | image | css | js | …"),
    sa.Column("internal", sa.Boolean, comment="The target is part of the site"),
    sa.Column("anchor", sa.String, comment="Anchor text"),
    sa.Column("rel", sa.String, comment="rel attribute"),
    sa.Column("nofollow", sa.Boolean, comment="rel=nofollow (or the page's nofollow)"),
    sa.Column("position", sa.String, comment="nav | header | footer | sidebar; NULL — content"),
    sa.Column("origin", sa.String, comment="html | rendered | html & rendered; images: css background"),
    comment="One row per link, resource or directive between two URLs of a crawl",
)
