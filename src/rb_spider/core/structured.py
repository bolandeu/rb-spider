"""Structured data: JSON-LD, Microdata and RDFa found on a page, validated against Schema.org and Google's
rich result features — at crawl time, in the parser workers.

JSON-LD is read here straight from the parsed tree (script elements + json): extruct would parse the whole page
again with lxml, and parsing is what a crawl's speed is bound by. Microdata and RDFa come from extruct (extra
`rb-spider[structured]`, `uniform=True` gives them JSON-LD's shape), imported only when asked for. A page keeps
a summary, not its items: formats, types, counts, the first MAX_MESSAGES messages and each rich result feature's
status (`pages.sd_*`). The items themselves are shown by `spider url` for crawls with stored HTML.

The reports at the end run in the main process; SQLAlchemy is imported inside them, so the workers don't load it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any

from selectolax.lexbor import LexborHTMLParser

from .sqltext import count_if

if TYPE_CHECKING:
    import sqlalchemy as sa

FORMATS = ("json-ld", "microdata", "rdfa")
MAX_MESSAGES = 50
_SCHEMA_PREFIXES = ("https://schema.org/", "http://schema.org/", "schema:")
_OLD_VOCABULARY = "data-vocabulary.org"


@cache
def vocabulary() -> dict:
    """data/schemaorg.json (scripts/build_schemaorg.py): types → parents, properties → domains, superseded."""
    return json.loads(resources.files("rb_spider.data").joinpath("schemaorg.json").read_text(encoding="utf-8"))


@cache
def ancestors(type_name: str) -> frozenset[str]:
    """The type and every type above it (Restaurant → FoodEstablishment → LocalBusiness → … → Thing)."""
    types = vocabulary()["types"]
    found, stack = {type_name}, list(types.get(type_name, []))
    while stack:
        parent = stack.pop()
        if parent not in found:
            found.add(parent)
            stack.extend(types.get(parent, []))
    return frozenset(found)


# Google rich result features (developers.google.com/search/docs/appearance/structured-data, 2026): the types that
# make one, required properties (errors when missing), recommended (warnings), and "one of" groups — at least one
# property of the group is required. The main features only; it is not Google's validator.
@dataclass(frozen=True)
class Feature:
    name: str
    types: tuple[str, ...]
    required: tuple[str, ...] = ()
    recommended: tuple[str, ...] = ()
    one_of: tuple[tuple[str, ...], ...] = ()


FEATURES = (
    Feature("Article", ("Article",), recommended=("author", "datePublished", "dateModified", "headline", "image")),
    Feature("Breadcrumb", ("BreadcrumbList",), required=("itemListElement",)),
    Feature("Product", ("Product",), required=("name",), one_of=(("offers", "review", "aggregateRating"),),
            recommended=("image", "description", "sku", "brand", "offers", "aggregateRating", "review")),
    Feature("Offer", ("Offer",), required=("price", "priceCurrency"), recommended=("availability", "url")),
    Feature("Review", ("Review",), required=("author", "reviewRating"), recommended=("datePublished",)),
    Feature("AggregateRating", ("AggregateRating",), required=("ratingValue",),
            one_of=(("ratingCount", "reviewCount"),), recommended=("bestRating", "worstRating")),
    Feature("Recipe", ("Recipe",), required=("name", "image"),
            recommended=("author", "datePublished", "description", "recipeIngredient", "recipeInstructions",
                         "totalTime", "recipeYield", "aggregateRating", "nutrition")),
    Feature("Event", ("Event",), required=("name", "startDate", "location"),
            recommended=("description", "endDate", "eventStatus", "image", "offers", "organizer", "performer")),
    Feature("FAQ", ("FAQPage",), required=("mainEntity",)),
    Feature("Question", ("Question",), required=("name", "acceptedAnswer")),
    Feature("JobPosting", ("JobPosting",), required=("datePosted", "description", "hiringOrganization", "jobLocation",
                                                     "title"),
            recommended=("baseSalary", "employmentType", "identifier", "validThrough")),
    Feature("LocalBusiness", ("LocalBusiness",), required=("name", "address"),
            recommended=("telephone", "url", "geo", "openingHoursSpecification", "priceRange", "image")),
    Feature("Organization", ("Organization",), recommended=("name", "url", "logo")),
    Feature("Video", ("VideoObject",), required=("name", "thumbnailUrl", "uploadDate"),
            recommended=("description", "contentUrl", "embedUrl", "duration")),
    Feature("SoftwareApp", ("SoftwareApplication",), required=("name",), one_of=(("offers", "aggregateRating", "review"),),
            recommended=("applicationCategory", "operatingSystem")),
    Feature("Course", ("Course",), required=("name", "description"), recommended=("provider",)),
    Feature("Dataset", ("Dataset",), required=("name", "description")),
)  # fmt: skip


@dataclass
class Result:
    formats: list[str] = field(default_factory=list)
    types: dict[str, None] = field(default_factory=dict)  # in order found
    parse_errors: int = 0
    messages: list[tuple[str, str, str, str, str]] = field(default_factory=list)  # severity, scope, type, prop, text
    counts: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(("errors", "warnings", "rich_errors", "rich_warnings"), 0)
    )
    features: dict[str, str] = field(default_factory=dict)  # feature -> "error" | "warning" | "ok"
    items: list[dict] = field(default_factory=list)

    def add(self, severity: str, scope: str, type_name: str, prop: str, text: str) -> None:
        key = ("rich_" if scope == "google" else "") + ("errors" if severity == "error" else "warnings")
        self.counts[key] += 1
        if len(self.messages) < MAX_MESSAGES:
            self.messages.append((severity, scope, type_name, prop, text))

    def columns(self) -> dict[str, Any]:
        """The `pages` columns of this result."""
        return {
            "sd_formats": f",{','.join(self.formats)}," if self.formats else "",
            "sd_types": f",{','.join(self.types)}," if self.types else None,
            "sd_parse_errors": self.parse_errors,
            "sd_errors": self.counts["errors"],
            "sd_warnings": self.counts["warnings"],
            "sd_rich_errors": self.counts["rich_errors"],
            "sd_rich_warnings": self.counts["rich_warnings"],
            "sd_messages": json.dumps(self.messages, ensure_ascii=False) if self.messages else None,
            "sd_features": json.dumps(self.features, ensure_ascii=False) if self.features else None,
        }


def _json_ld(tree: LexborHTMLParser, result: Result) -> list[dict]:
    items: list[dict] = []
    for script in tree.css("script[type]"):
        if (script.attributes.get("type") or "").split(";")[0].strip().lower() != "application/ld+json":
            continue
        try:
            data = json.loads(script.text(deep=True) or "")
        except ValueError:
            result.parse_errors += 1
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict):
                graph = node.get("@graph")
                items.extend(n for n in (graph if isinstance(graph, list) else [node]) if isinstance(n, dict))
    return items


def _extruct(body: bytes, url: str, syntaxes: list[str], result: Result) -> dict[str, list[dict]]:
    import extruct  # extra `rb-spider[structured]`: only crawls collecting Microdata / RDFa import it

    try:
        return extruct.extract(body, base_url=url, syntaxes=syntaxes, uniform=True)
    except Exception:  # extruct raises whatever its parsers do on broken markup
        result.parse_errors += 1
        return {}


def _type_names(node: dict) -> list[str]:
    raw = node.get("@type")
    names = raw if isinstance(raw, list) else [raw] if raw else []
    found = []
    for name in names:
        if isinstance(name, str):
            for prefix in _SCHEMA_PREFIXES:
                name = name.removeprefix(prefix)
            found.append(name)
    return found


def _is_schema_org(node: dict, inherited: bool) -> bool:
    context = node.get("@context")
    if context is None:
        return inherited
    text = json.dumps(context) if not isinstance(context, str) else context
    return "schema.org" in text


def _check(node: dict, result: Result, schema_org: bool) -> None:
    vocab = vocabulary()
    types = _type_names(node)
    if _OLD_VOCABULARY in json.dumps([node.get("@context"), node.get("@type")]):
        result.add("warning", "schema.org", ", ".join(types), "", "data-vocabulary.org устарел: используйте schema.org")
        schema_org = False
    schema_org = _is_schema_org(node, schema_org)
    known = [t for t in types if t in vocab["types"]]
    for type_name in types:
        result.types.setdefault(type_name, None)
        if schema_org and type_name not in vocab["types"]:
            result.add("error", "schema.org", type_name, "", f"тип {type_name} не существует в Schema.org")
        elif schema_org and type_name in vocab["superseded"]:
            result.add("warning", "schema.org", type_name, "", f"тип {type_name} устарел (superseded)")
    lineage = frozenset().union(*(ancestors(t) for t in known)) if known else frozenset()
    for prop, value in node.items():
        if prop.startswith("@"):
            continue
        name = prop
        for prefix in _SCHEMA_PREFIXES:
            name = name.removeprefix(prefix)
        if schema_org and known and ":" not in name:  # "http://ogp.me/ns#title": another vocabulary
            domains = vocab["properties"].get(name)
            if domains is None:
                result.add("error", "schema.org", known[0], name, f"свойства {name} нет в Schema.org")
            elif name in vocab["superseded"]:  # a retired property is a warning wherever it's used
                result.add("warning", "schema.org", known[0], name, f"свойство {name} устарело (superseded)")
            elif domains and not lineage.intersection(domains):
                result.add("error", "schema.org", known[0], name, f"свойство {name} не определено для типа {known[0]}")
        for child in value if isinstance(value, list) else [value]:
            if isinstance(child, dict):
                _check(child, result, schema_org)
    if schema_org and known:
        _rich(node, known, lineage, result)


def _present(node: dict, prop: str) -> bool:
    value = node.get(prop, node.get(f"http://schema.org/{prop}", node.get(f"https://schema.org/{prop}")))
    return value not in (None, "", [], {})


def _rich(node: dict, known: list[str], lineage: frozenset[str], result: Result) -> None:
    for feature in FEATURES:
        if not lineage.intersection(feature.types):
            continue
        status = result.features.get(feature.name, "ok")
        for prop in feature.required:
            if not _present(node, prop):
                result.add("error", "google", known[0], prop, f"{feature.name}: нет обязательного свойства {prop}")
                status = "error"
        for group in feature.one_of:
            if not any(_present(node, prop) for prop in group):
                result.add("error", "google", known[0], "|".join(group),
                           f"{feature.name}: нужно хотя бы одно из свойств {', '.join(group)}")  # fmt: skip
                status = "error"
        for prop in feature.recommended:
            if not _present(node, prop):
                result.add("warning", "google", known[0], prop, f"{feature.name}: нет рекомендуемого свойства {prop}")
                status = "warning" if status == "ok" else status
        result.features[feature.name] = status


def extract(
    tree: LexborHTMLParser, body: bytes, url: str, formats: tuple[str, ...], keep_items: bool = False
) -> Result:
    """Structured data of one page in the chosen formats, validated. `keep_items` — keep the items too."""
    result = Result()
    by_format: dict[str, list[dict]] = {}
    if "json-ld" in formats:
        by_format["json-ld"] = _json_ld(tree, result)
    others = [f for f in formats if f in ("microdata", "rdfa")]
    if others:
        extracted = _extruct(body, url, others, result)
        for name in others:
            by_format[name] = [item for item in extracted.get(name, []) if isinstance(item, dict)]
    for name, items in by_format.items():
        if items:
            result.formats.append(name)
        for item in items:
            _check(item, result, schema_org=name != "json-ld")
            if keep_items:
                result.items.append({"format": name, **item})
    return result


# --- reports over a stored crawl ---------------------------------------------------------------

_WITH_DATA = (
    "SELECT url, sd_messages, sd_features FROM spider_pages WHERE crawl_id = :crawl_id AND NOT coalesce(external, FALSE)"
    " AND sd_formats IS NOT NULL ORDER BY url"
)


def summary(conn: sa.Connection, crawl_id: int, report: str) -> list[dict]:
    """Screaming Frog's Structured Data reports, streamed over the crawl's pages (counters only in memory).

    `validation` — every message with the number of URLs that have it and an example URL (a page keeps its
    first MAX_MESSAGES messages); `features` — each rich result feature with its URLs, with errors, with warnings.
    """
    import sqlalchemy as sa  # here, not at the top: the parser workers import this module and must stay small

    from . import storage

    rows = storage.streamed(conn, 1000).execute(sa.text(_WITH_DATA), {"crawl_id": crawl_id})
    if report == "features":
        features: dict[str, dict[str, int]] = {}
        for _, _, raw in rows:
            for name, status in json.loads(raw or "{}").items():
                entry = features.setdefault(name, {"urls": 0, "error": 0, "warning": 0})
                entry["urls"] += 1
                if status in ("error", "warning"):
                    entry[status] += 1
        return [{"feature": name, "urls": e["urls"], "with_errors": e["error"], "with_warnings": e["warning"]}
                for name, e in sorted(features.items(), key=lambda item: -item[1]["urls"])]  # fmt: skip
    messages: dict[tuple, dict] = {}
    for url, raw, _ in rows:
        for message in {tuple(m) for m in json.loads(raw or "[]")}:
            entry = messages.setdefault(message, {"urls": 0, "example": url})
            entry["urls"] += 1
    order = {"error": 0, "warning": 1}
    return [{"severity": m[0], "scope": m[1], "type": m[2], "property": m[3], "message": m[4], **e}
            for m, e in sorted(messages.items(), key=lambda item: (order[item[0][0]], -item[1]["urls"], item[0]))]  # fmt: skip


def counts(conn: sa.Connection, crawl_id: int) -> dict[str, int]:
    """HTML pages with / without structured data and by format — Screaming Frog's Structured Data filters."""
    import sqlalchemy as sa

    row = conn.execute(
        sa.text(
            f"SELECT count(*), {count_if("sd_formats <> ''")}, {count_if("sd_formats LIKE '%,json-ld,%'")},"  # noqa: S608 — fixed text
            f" {count_if("sd_formats LIKE '%,microdata,%'")}, {count_if("sd_formats LIKE '%,rdfa,%'")} FROM spider_pages"
            " WHERE crawl_id = :crawl_id AND NOT coalesce(external, FALSE) AND sd_formats IS NOT NULL"
        ),
        {"crawl_id": crawl_id},
    ).one()
    if not row[0]:
        return {}
    return {"contains": row[1] or 0, "missing": row[0] - (row[1] or 0), "json-ld": row[2] or 0,
            "microdata": row[3] or 0, "rdfa": row[4] or 0}  # fmt: skip
