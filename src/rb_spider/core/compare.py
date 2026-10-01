"""Comparing two crawls — Screaming Frog's Compare mode and Change Detection.

Both crawls live in the same database, so every answer is one SQL query joining their rows by URL: nothing is
loaded into memory whatever the size of the sites. An issue's URLs fall into Screaming Frog's four groups:

- added — the URL was in both crawls, and is in the issue now but wasn't before;
- new — the URL is new to the crawl and has the issue;
- removed — the URL is in both crawls, and had the issue but no longer has it;
- missing — the URL had the issue and is gone from the crawl.

Change Detection compares the fields in `compare.fields` of URLs present in both crawls. With URL Mapping
(`compare.url_mapping`) the old crawl's URLs are first rewritten into the new crawl's (staging vs production, a
domain move, a new URL structure).
"""

from __future__ import annotations

import re
from typing import Literal, get_args

import sqlalchemy as sa

from . import issues, storage
from .errors import InvalidArguments

# field -> SQL expression over a pages row (alias p)
FIELDS = {
    "indexability": "coalesce(p.indexability_status, 'Indexable')",
    "status_code": "p.status_code",
    "title": "p.title",
    "meta_description": "p.meta_description",
    "h1": "p.h1",
    "h2": "p.h2",
    "canonical": "p.canonical_url",
    "directives": "p.robots_directives",
    "word_count": "p.word_count",
    "content": "p.content_md5",
    "depth": "p.depth",
    "inlinks": "p.inlinks",
    "unique_inlinks": "p.unique_inlinks",
    "internal_outlinks": "p.internal_outlinks",
    "unique_outlinks": "p.unique_outlinks",
    "external_outlinks": "p.external_outlinks",
    "structured_data_types": "p.sd_types",
}
Status = Literal["added", "new", "removed", "missing"]
STATUSES: tuple[str, ...] = get_args(Status)
_OWN = "NOT coalesce(external, FALSE)"
_BATCH = 5000


class Mapping:
    """URL Mapping: the old crawl's URLs as the new crawl spells them (`compare.url_mapping`, regex → replacement).

    The rules go over the old crawl's URLs once, a batch at a time; only the URLs they change land in a temporary
    table `cmp_old (orig → url)`, so queries translate an old URL with one index lookup. Without rules every piece
    of SQL below is the plain URL-to-URL comparison.
    """

    def __init__(self, conn: sa.Connection, old: int, rules: list[tuple[str, str]]) -> None:
        self.active = bool(rules)
        if not self.active:
            return
        compiled = [(re.compile(pattern), replace) for pattern, replace in rules]
        temp = "temp" if storage.is_sqlite(conn) else "pg_temp"
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {temp}.cmp_old")
        conn.exec_driver_sql("CREATE TEMP TABLE cmp_old (orig TEXT PRIMARY KEY, url TEXT NOT NULL)")
        conn.exec_driver_sql(
            f"CREATE INDEX {'temp.' if storage.is_sqlite(conn) else ''}cmp_old_by_url ON cmp_old (url)"
        )
        select = sa.text(
            "SELECT url FROM spider_pages WHERE crawl_id = :old AND url > :after ORDER BY url LIMIT :limit"
        )
        insert = sa.text("INSERT INTO cmp_old (orig, url) VALUES (:orig, :url)")
        after = ""
        while batch := conn.execute(select, {"old": old, "after": after, "limit": _BATCH}).scalars().all():
            after = batch[-1]
            changed = []
            for url in batch:
                mapped = url
                for pattern, replace in compiled:
                    mapped = pattern.sub(replace, mapped)
                if mapped != url:
                    changed.append({"orig": url, "url": mapped})
            if changed:
                conn.execute(insert, changed)

    def old(self, column: str) -> str:
        """An old crawl's URL column as the new crawl spells it."""
        if not self.active:
            return column
        return f"coalesce((SELECT cm.url FROM cmp_old cm WHERE cm.orig = {column}), {column})"  # noqa: S608 — a column name

    def back(self, column: str) -> str:
        """A new crawl's URL column as the old crawl spelled it (the first old URL mapped onto it, else itself)."""
        if not self.active:
            return column
        return f"coalesce((SELECT cm.orig FROM cmp_old cm WHERE cm.url = {column} LIMIT 1), {column})"  # noqa: S608

    def urls(self, crawl: str) -> str:
        """The crawl's own URLs — the old one's as the new crawl spells them."""
        column = self.old("p.url") if crawl == "old" else "p.url"
        own = "NOT coalesce(p.external, FALSE)"
        return f"SELECT {column} AS url FROM spider_pages p WHERE p.crawl_id = :{crawl} AND {own}"  # noqa: S608 — fixed text


def _rules(mapping: list | None) -> list[tuple[str, str]]:
    return [(m.pattern, m.replace) if hasattr(m, "pattern") else tuple(m) for m in mapping or []]


def summary(engine: sa.Engine, old: int, new: int, fields: list[str], mapping: list | None = None) -> dict:
    """URL counts, every rule's four groups (rules with something in either crawl) and changed fields."""
    params = {"old": old, "new": new}
    with engine.begin() as conn:
        m = Mapping(conn, old, _rules(mapping))
        old_urls, new_urls = m.urls("old"), m.urls("new")
        urls = conn.execute(
            sa.text(
                f"SELECT (SELECT count(*) FROM ({old_urls}) a), (SELECT count(*) FROM ({new_urls}) b),"  # noqa: S608
                f" (SELECT count(*) FROM ({new_urls}) n WHERE n.url NOT IN ({old_urls})),"
                f" (SELECT count(*) FROM ({old_urls}) o WHERE o.url NOT IN ({new_urls}))"
            ),
            params,
        ).one()
        # one pass: every (rule, URL) with whether it was flagged before / now, and whether the URL was crawled
        rows = conn.execute(
            sa.text(
                f"WITH oldpages AS ({old_urls}), newpages AS ({new_urls}),"  # noqa: S608
                " f AS (SELECT i.code, CASE WHEN i.crawl_id = :old THEN "
                f"{m.old('i.url')} ELSE i.url END AS url, CASE WHEN i.crawl_id = :old THEN 1 ELSE 0 END AS was,"
                " CASE WHEN i.crawl_id = :new THEN 1 ELSE 0 END AS is_now"
                "   FROM spider_issues i WHERE i.crawl_id IN (:old, :new)),"
                " x AS (SELECT code, url, max(was) AS was, max(is_now) AS is_now FROM f GROUP BY code, url),"
                # flags as 0 / 1, not booleans: one spelling for SQLite and PostgreSQL (`AND` becomes `*`)
                " y AS (SELECT code, was, is_now, CASE WHEN url IN (SELECT url FROM oldpages) THEN 1 ELSE 0 END AS in_old,"
                "   CASE WHEN url IN (SELECT url FROM newpages) THEN 1 ELSE 0 END AS in_new FROM x)"
                " SELECT code, sum(was), sum(is_now), sum(is_now * (1 - was) * in_old), sum(is_now * (1 - in_old)),"
                " sum(was * (1 - is_now) * in_new), sum(was * (1 - in_new)) FROM y GROUP BY code"
            ),
            params,
        ).all()
        changes = {name: conn.execute(sa.text(f"SELECT count(*) FROM ({_changed(name, m)}) c"), params).scalar_one()  # noqa: S608
                   for name in fields}  # fmt: skip
    order = {rule.code: i for i, rule in enumerate(issues.RULES)}
    found = []
    for code, before, after, added, fresh, removed, missing in sorted(rows, key=lambda r: order.get(r[0], 10**6)):
        rule = issues.BY_CODE.get(code)
        found.append({"code": code, "name": rule.name if rule else code, "old": before, "new": after,
                      "added": added, "new_urls": fresh, "removed": removed, "missing": missing})  # fmt: skip
    return {
        "urls": {"old": urls[0], "new": urls[1], "new_urls": urls[2], "missing_urls": urls[3]},
        "issues": found,
        "changes": changes,
    }


def _changed(field: str, m: Mapping) -> str:
    if field not in FIELDS:
        raise InvalidArguments(f"Unknown compare field '{field}': one of {', '.join(FIELDS)}.")
    expression = FIELDS[field]
    return (
        f"SELECT n.url, {expression.replace('p.', 'o.')} AS old, {expression.replace('p.', 'n.')} AS new"  # noqa: S608
        f" FROM spider_pages n JOIN spider_pages o ON o.crawl_id = :old AND o.url = {m.back('n.url')}"
        f" AND NOT coalesce(o.external, FALSE)"
        f" WHERE n.crawl_id = :new AND NOT coalesce(n.external, FALSE) AND n.parsed AND o.parsed"
        f" AND {expression.replace('p.', 'o.')} IS DISTINCT FROM {expression.replace('p.', 'n.')}"
    )


def _issue_urls(code: str, status: str, m: Mapping) -> str:
    issues.rule(code)
    if status not in STATUSES:
        raise InvalidArguments(f"--status: one of {', '.join(STATUSES)}.")
    presence = "IN" if status in ("added", "removed") else "NOT IN"
    if status in ("added", "new"):  # flagged now (new crawl), not before (old crawl): URLs in the new crawl's terms
        return (
            "SELECT DISTINCT i.url FROM spider_issues i WHERE i.crawl_id = :new AND i.code = :code"  # noqa: S608
            f" AND i.url {presence} ({m.urls('old')})"
            " AND NOT EXISTS (SELECT 1 FROM spider_issues j WHERE j.crawl_id = :old AND j.code = :code"
            f" AND j.url = {m.back('i.url')})"
        )
    # flagged before, not now: the old crawl's own URLs
    return (
        "SELECT DISTINCT i.url FROM spider_issues i WHERE i.crawl_id = :old AND i.code = :code"  # noqa: S608
        f" AND {m.old('i.url')} {presence} ({m.urls('new')})"
        " AND NOT EXISTS (SELECT 1 FROM spider_issues j WHERE j.crawl_id = :new AND j.code = :code"
        f" AND j.url = {m.old('i.url')})"
    )


def details(
    engine: sa.Engine,
    old: int,
    new: int,
    *,
    issue: str | None = None,
    status: str | None = None,
    field: str | None = None,
    urls: str | None = None,
    limit: int | None = None,
    mapping: list | None = None,
) -> tuple[int, list[dict]]:
    """One list: an issue's URLs in one group, the URLs whose `field` changed, or the new / missing URLs."""
    if sum(x is not None for x in (issue, field, urls)) != 1:
        raise InvalidArguments("Choose one list: --issue CODE --status …, --field NAME or --urls new|missing.")
    params = {"old": old, "new": new, "code": issue, "limit": storage.NO_LIMIT if limit is None else limit}
    with engine.begin() as conn:
        m = Mapping(conn, old, _rules(mapping))
        if issue is not None:
            query = _issue_urls(issue, status or "new", m)
        elif field is not None:
            query = _changed(field, m)
        elif urls == "new":
            query = f"SELECT url FROM ({m.urls('new')}) n WHERE url NOT IN ({m.urls('old')})"  # noqa: S608
        elif urls == "missing":  # the old crawl's own URLs
            query = (
                "SELECT o.url FROM spider_pages o WHERE o.crawl_id = :old AND NOT coalesce(o.external, FALSE)"  # noqa: S608
                f" AND {m.old('o.url')} NOT IN ({m.urls('new')})"
            )
        else:
            raise InvalidArguments("--urls: new or missing.")
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query}) q"), params).scalar_one()  # noqa: S608
        rows = conn.execute(sa.text(f"SELECT * FROM ({query}) q ORDER BY url LIMIT :limit"), params).mappings()  # noqa: S608
        return total, [dict(row) for row in rows]
