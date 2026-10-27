"""Public API: fetch pages with spider's engine — no crawl.

    from rb_spider.fetch import fetch, fetch_many, CrawlSettings

    page = fetch("https://example.com/old")                  # final_url, status, redirects, seo…
    page = fetch(url, render=True, include="text,links")     # through a browser (rb-spider[render])
    settings = CrawlSettings(proxy_urls=["http://user:{password}@proxy:8000"], user_agent="googlebot")
    for page in fetch_many(urls, settings, concurrency=20):  # in input order, flat memory
        ...

`include` adds `headers`, `links`, `resources`, `text`, `markdown`, `html` to the always-present SEO data.
`store=True` uses the page storage of `spider fetch` (ADR 0001; off by default here, on in the CLI): a URL stored
within `max_age` days comes from it with `from_cache` set, `fresh=True` fetches anyway and stores the new fetch.
A URL that doesn't answer comes back with `error` set, not as an exception. The same from any
language: `spider fetch --json` (JSON Lines).
"""

from .core.fetch import INCLUDE, FetchResult, fetch, fetch_many, fetch_stream
from .core.settings import CrawlSettings

__all__ = ["INCLUDE", "CrawlSettings", "FetchResult", "fetch", "fetch_many", "fetch_stream"]
