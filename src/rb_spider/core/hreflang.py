"""Hreflang: valid codes and the Hreflang report — Screaming Frog's Reports → Hreflang.

Annotations are link rows of kind "hreflang" (the code in `link_rows.hreflang`), from `<link rel="alternate"
hreflang>` and the `Link` header. The report filters them in SQL and returns one page of rows plus the total,
so a site with millions of annotations never loads them all. The checks themselves are rules in `issues`.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

import sqlalchemy as sa

# ISO 639-1 languages and ISO 3166-1 alpha-2 regions (pycountry 26.2.16). Google reads hreflang as
# language[-region]; "UK" is not a region (GB is), "iw"/"in"/"ji" are retired codes.
_LANGUAGE_TABLE = (
    "aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en "
    "eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja "
    "jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb "
    "nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg sh si sk sl sm sn so "
    "sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu"
)
_REGION_TABLE = (
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ "
    "CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO "
    "FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE "
    "JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO "
    "MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW "
    "PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM "
    "TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
)
LANGUAGES = frozenset(_LANGUAGE_TABLE.split())
REGIONS = frozenset(_REGION_TABLE.split())
# language, optional ISO 15924 script (zh-Hant), optional region
_CODE = re.compile(r"^([a-z]{2})(?:-[a-z]{4})?(?:-([a-z]{2}))?$", re.IGNORECASE)


def valid_code(code: str) -> bool:
    """`x-default`, or an ISO 639-1 language with an optional script and ISO 3166-1 alpha-2 region."""
    if code.lower() == "x-default":
        return True
    match = _CODE.match(code.strip())
    if not match:
        return False
    language, region = match.group(1).lower(), match.group(2)
    return language in LANGUAGES and (region is None or region.upper() in REGIONS)


Only = Literal[
    "all", "non_200", "unlinked", "missing_return", "inconsistent", "non_canonical", "noindex_return", "missing"
]
ONLY: tuple[str, ...] = get_args(Only)

# One row per annotation: the page, the code, the alternate URL and what the crawl knows about it.
_ROWS = """
    SELECT s.url AS source, l.hreflang, t.url AS target, p.status_code AS target_status, p.blocked AS target_blocked,
           p.indexability_status AS target_indexability,
           CASE WHEN l.source_id = l.target_id THEN NULL ELSE EXISTS (SELECT 1 FROM link_rows r
               WHERE r.crawl_id = l.crawl_id AND r.kind = 'hreflang' AND r.source_id = l.target_id
               AND r.target_id = l.source_id) END AS return_link
    FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id
    LEFT JOIN pages p ON p.crawl_id = l.crawl_id AND p.url = t.url
    WHERE l.crawl_id = :crawl_id AND l.kind = 'hreflang'
"""
FILTERS = {
    "all": "1",
    "non_200": "p.url IS NOT NULL AND (p.status_code <> 200 OR p.blocked IS NOT NULL)",
    "unlinked": "NOT coalesce(p.external, 1) AND NOT EXISTS (SELECT 1 FROM link_rows h WHERE h.crawl_id = l.crawl_id"
    " AND h.target_id = l.target_id AND h.kind = 'hyperlink')",
    "missing_return": "l.source_id <> l.target_id AND p.parsed AND p.status_code = 200 AND NOT EXISTS (SELECT 1"
    " FROM link_rows r WHERE r.crawl_id = l.crawl_id AND r.kind = 'hreflang' AND r.source_id = l.target_id"
    " AND r.target_id = l.source_id)",
    # a link back to a page with a code that page doesn't give itself
    "inconsistent": "l.source_id <> l.target_id AND EXISTS (SELECT 1 FROM link_rows m WHERE m.crawl_id = l.crawl_id"
    " AND m.kind = 'hreflang' AND m.source_id = l.target_id AND m.target_id = l.target_id) AND NOT EXISTS (SELECT 1"
    " FROM link_rows m WHERE m.crawl_id = l.crawl_id AND m.kind = 'hreflang' AND m.source_id = l.target_id"
    " AND m.target_id = l.target_id AND lower(m.hreflang) = lower(l.hreflang))",
    "non_canonical": "l.source_id <> l.target_id AND p.canonical_url IS NOT NULL AND p.canonical_url <> p.url",
    "noindex_return": "l.source_id <> l.target_id AND (p.robots_directives LIKE '%,noindex,%'"
    " OR p.robots_directives LIKE '%,none,%')",
}
# HTML pages of the site with no annotation at all ("missing"): other columns are empty
_MISSING = """
    SELECT p.url AS source, NULL AS hreflang, NULL AS target, NULL AS target_status, NULL AS target_blocked,
           NULL AS target_indexability, NULL AS return_link
    FROM pages p WHERE p.crawl_id = :crawl_id AND NOT coalesce(p.external, 0) AND p.parsed AND p.status_code = 200
    AND p.content_type LIKE '%html%' AND NOT EXISTS (SELECT 1 FROM urls u JOIN link_rows l ON l.crawl_id = u.crawl_id
        AND l.source_id = u.id AND l.kind = 'hreflang' WHERE u.crawl_id = p.crawl_id AND u.url = p.url)
"""


def _query(only: str) -> str:
    return _MISSING if only == "missing" else f"{_ROWS} AND ({FILTERS[only]})"


def report(engine: sa.Engine, crawl_id: int, only: str = "all", limit: int | None = None) -> tuple[int, list[dict]]:
    """Hreflang annotations matching `only` (see ONLY): the total and the first `limit` rows."""
    query = _query(only)
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query})"), {"crawl_id": crawl_id}).scalar_one()  # noqa: S608 — fixed text
        rows = conn.execute(
            sa.text(f"{query} ORDER BY source, target LIMIT :limit"),
            {"crawl_id": crawl_id, "limit": -1 if limit is None else limit},
        ).mappings()
        found = [
            {**row, "return_link": None if row["return_link"] is None else bool(row["return_link"])} for row in rows
        ]
    return total, found


def counts(conn: sa.Connection, crawl_id: int) -> dict[str, int]:
    """HTML pages of the site with / without hreflang — Screaming Frog's Contains Hreflang / Missing."""
    total = conn.execute(
        sa.text(
            "SELECT count(*) FROM pages WHERE crawl_id = :crawl_id AND NOT coalesce(external, 0) AND parsed"
            " AND status_code = 200 AND content_type LIKE '%html%'"
        ),
        {"crawl_id": crawl_id},
    ).scalar_one()
    missing = conn.execute(sa.text(f"SELECT count(*) FROM ({_MISSING})"), {"crawl_id": crawl_id}).scalar_one()  # noqa: S608
    return {"contains": total - missing, "missing": missing} if total - missing else {}
