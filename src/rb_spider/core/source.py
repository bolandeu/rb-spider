"""View Source: a page's HTML as the server sent it and as the browser left it after JavaScript, and what changed.

Both come from the stored-HTML file (`crawl.store_html`; the DOM only for pages the crawl rendered).
"""

from __future__ import annotations

import difflib

from . import storage
from .errors import InvalidArguments

MAX_DIFF_LINES = 2000


def view(crawl_id: int, url: str, mode: str) -> dict:
    """mode: raw — the response body; rendered — the DOM; diff — a unified diff of the two, line by line."""
    raw = storage.get_html(crawl_id, url)
    if raw is None:
        raise InvalidArguments(
            f"No stored HTML of {url} in crawl #{crawl_id} — crawl with --store-html (crawl.store_html) to keep it."
        )
    if mode == "raw":
        return {"html": raw.decode("utf-8", "replace")}
    dom = storage.get_html(crawl_id, url, rendered=True)
    if dom is None:
        raise InvalidArguments(
            f"{url} wasn't rendered in crawl #{crawl_id} — its DOM is kept only for pages rendered with --store-html"
            " (crawl.render = always | auto)."
        )
    if mode == "rendered":
        return {"html": dom.decode("utf-8", "replace")}
    lines = difflib.unified_diff(raw.decode("utf-8", "replace").splitlines(), dom.decode("utf-8", "replace").splitlines(),
                                 fromfile="raw", tofile="rendered", lineterm="")  # fmt: skip
    diff = list(lines)
    return {"diff": diff[:MAX_DIFF_LINES], "truncated": len(diff) > MAX_DIFF_LINES}
