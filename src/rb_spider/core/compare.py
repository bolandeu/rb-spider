"""Comparing two crawls — Screaming Frog's Compare mode and Change Detection.

Both crawls live in the same database, so every answer is one SQL query joining their rows by URL: nothing is
loaded into memory whatever the size of the sites. An issue's URLs fall into Screaming Frog's four groups:

- added — the URL was in both crawls, and is in the issue now but wasn't before;
- new — the URL is new to the crawl and has the issue;
- removed — the URL is in both crawls, and had the issue but no longer has it;
- missing — the URL had the issue and is gone from the crawl.

Change Detection compares the fields in `compare.fields` of URLs present in both crawls.
"""

from __future__ import annotations

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


def _urls(crawl: str) -> str:
    return f"SELECT url FROM pages WHERE crawl_id = :{crawl} AND {_OWN}"  # noqa: S608 — fixed text


def summary(engine: sa.Engine, old: int, new: int, fields: list[str]) -> dict:
    """URL counts, every rule's four groups (rules with something in either crawl) and changed fields."""
    params = {"old": old, "new": new}
    with engine.connect() as conn:
        urls = conn.execute(
            sa.text(
                f"SELECT (SELECT count(*) FROM ({_urls('old')})), (SELECT count(*) FROM ({_urls('new')})),"  # noqa: S608
                f" (SELECT count(*) FROM ({_urls('new')}) n WHERE n.url NOT IN ({_urls('old')})),"
                f" (SELECT count(*) FROM ({_urls('old')}) o WHERE o.url NOT IN ({_urls('new')}))"
            ),
            params,
        ).one()
        # one pass: every (rule, URL) with whether it was flagged before / now, and whether the URL was crawled
        rows = conn.execute(
            sa.text(
                f"WITH oldpages AS ({_urls('old')}), newpages AS ({_urls('new')}),"  # noqa: S608
                " x AS (SELECT code, url, max(crawl_id = :old) AS was, max(crawl_id = :new) AS is_now FROM issues"
                "   WHERE crawl_id IN (:old, :new) GROUP BY code, url),"
                " y AS (SELECT code, was, is_now, url IN (SELECT url FROM oldpages) AS in_old,"
                "   url IN (SELECT url FROM newpages) AS in_new FROM x)"
                " SELECT code, sum(was), sum(is_now), sum(is_now AND NOT was AND in_old), sum(is_now AND NOT in_old),"
                " sum(was AND NOT is_now AND in_new), sum(was AND NOT in_new) FROM y GROUP BY code"
            ),
            params,
        ).all()
        changes = {name: conn.execute(sa.text(f"SELECT count(*) FROM ({_changed(name)})"), params).scalar_one()  # noqa: S608
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


def _changed(field: str) -> str:
    if field not in FIELDS:
        raise InvalidArguments(f"Unknown compare field '{field}': one of {', '.join(FIELDS)}.")
    expression = FIELDS[field]
    return (
        f"SELECT n.url, {expression.replace('p.', 'o.')} AS old, {expression.replace('p.', 'n.')} AS new"  # noqa: S608
        f" FROM pages n JOIN pages o ON o.crawl_id = :old AND o.url = n.url AND NOT coalesce(o.external, FALSE)"
        f" WHERE n.crawl_id = :new AND NOT coalesce(n.external, FALSE) AND n.parsed AND o.parsed"
        f" AND {expression.replace('p.', 'o.')} IS DISTINCT FROM {expression.replace('p.', 'n.')}"
    )


def _issue_urls(code: str, status: str) -> str:
    issues.rule(code)
    if status not in STATUSES:
        raise InvalidArguments(f"--status: one of {', '.join(STATUSES)}.")
    now, before = ("new", "old") if status in ("added", "new") else ("old", "new")
    presence = "IN" if status in ("added", "removed") else "NOT IN"
    return (
        f"SELECT DISTINCT i.url FROM issues i WHERE i.crawl_id = :{now} AND i.code = :code"  # noqa: S608
        f" AND i.url {presence} ({_urls(before)})"
        f" AND NOT EXISTS (SELECT 1 FROM issues j WHERE j.crawl_id = :{before} AND j.code = :code AND j.url = i.url)"
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
) -> tuple[int, list[dict]]:
    """One list: an issue's URLs in one group, the URLs whose `field` changed, or the new / missing URLs."""
    if sum(x is not None for x in (issue, field, urls)) != 1:
        raise InvalidArguments("Choose one list: --issue CODE --status …, --field NAME or --urls new|missing.")
    if issue is not None:
        query = _issue_urls(issue, status or "new")
    elif field is not None:
        query = _changed(field)
    elif urls == "new":
        query = f"SELECT url FROM ({_urls('new')}) WHERE url NOT IN ({_urls('old')})"  # noqa: S608
    elif urls == "missing":
        query = f"SELECT url FROM ({_urls('old')}) WHERE url NOT IN ({_urls('new')})"  # noqa: S608
    else:
        raise InvalidArguments("--urls: new or missing.")
    params = {"old": old, "new": new, "code": issue, "limit": storage.NO_LIMIT if limit is None else limit}
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query})"), params).scalar_one()  # noqa: S608
        rows = conn.execute(sa.text(f"SELECT * FROM ({query}) ORDER BY url LIMIT :limit"), params).mappings()  # noqa: S608
        return total, [dict(row) for row in rows]
