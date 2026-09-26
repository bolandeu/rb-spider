"""Deterministic fake e-commerce site for crawler benchmarks (issue #2).

    uv run --project bench bench/bench_site.py serve --pages 100000 --workers 4
    uv run --project bench bench/bench_site.py build --pages 20000 --out "$TMPDIR/spider-stand"
    hostme "$TMPDIR/spider-stand" spider.bolandau.ru     # the VPS stand; delete the local copy after

`serve` renders pages on the fly (nothing on disk) — the default for local benches.
`build` writes static files for a static host; keep --out outside the repo, pages are ~60 KB each.
Same seed + params -> byte-identical pages. Structure: home, 10 top categories x 10
subcategories, paginated listings (24 products per page), product pages with menu,
breadcrumbs, related products, footer. Every page: meta robots noindex; robots.txt
disallows Googlebot/YandexBot (not the bench crawler).
"""

from __future__ import annotations

import argparse
import math
import multiprocessing
import random
import socket
from pathlib import Path

TOP, SUB, PER_PAGE, RELATED = 10, 10, 24, 8
STATIC = ["about", "contacts", "delivery", "payment", "returns", "faq", "blog", "news", "privacy", "terms"]
WORDS = [
    "краулер",
    "сайт",
    "страница",
    "ссылка",
    "индекс",
    "поиск",
    "товар",
    "каталог",
    "цена",
    "доставка",
    "скидка",
    "заказ",
    "качество",
    "гарантия",
    "отзыв",
    "бренд",
    "модель",
    "размер",
    "цвет",
    "материал",
    "склад",
    "наличие",
    "новинка",
    "lorem",
    "ipsum",
    "dolor",
    "sit",
    "amet",
    "consectetur",
    "adipiscing",
    "elit",
    "sed",
    "do",
    "eiusmod",
    "tempor",
]


class Site:
    def __init__(self, pages: int, page_kb: int, seed: int) -> None:
        self.seed, self.page_bytes = seed, page_kb * 1024
        fixed = 1 + TOP + TOP * SUB + len(STATIC)
        # products + listing pages ~= pages - fixed; listing pages ~= products / PER_PAGE
        self.products = max(PER_PAGE, int((pages - fixed) * PER_PAGE / (PER_PAGE + 1)))
        self.per_sub = math.ceil(self.products / (TOP * SUB))
        self.list_pages = math.ceil(self.per_sub / PER_PAGE)
        rng = random.Random(seed)
        self.corpus = " ".join(rng.choice(WORDS) for _ in range(400_000))  # ~3 MB to slice from

    @property
    def total(self) -> int:
        return 1 + TOP + TOP * SUB * (1 + self.list_pages - 1) + self.products + len(STATIC)

    # --- helpers -------------------------------------------------------------
    def _text(self, rng: random.Random, n: int) -> str:
        start = rng.randrange(0, len(self.corpus) - n - 1)
        return self.corpus[start : start + n]

    def _sub_of(self, pid: int) -> tuple[int, int]:
        s = min(pid // self.per_sub, TOP * SUB - 1)
        return s // SUB, s % SUB

    def _menu(self) -> str:
        items = "".join(f'<li><a href="/c/{t}/">Категория {t}</a></li>' for t in range(TOP))
        return f'<nav><ul><li><a href="/">Главная</a></li>{items}</ul></nav>'

    def _footer(self) -> str:
        return "<footer>" + "".join(f'<a href="/{s}.html">{s}</a> ' for s in STATIC) + "</footer>"

    def _page(self, rng: random.Random, title: str, h1: str, body: str, canonical: str) -> bytes:
        head = (
            f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{title}</title>'
            f'<meta name="description" content="{self._text(rng, 140)}">'
            f'<meta name="robots" content="noindex, nofollow"><link rel="canonical" href="{canonical}">'
            "</head><body>"
        )
        html = f"{head}{self._menu()}<h1>{h1}</h1>{body}"
        filler = self.page_bytes - len(html.encode()) - 200
        if filler > 0:
            paras = [f"<p>{self._text(rng, 600)}</p>" for _ in range(filler // 1100 + 1)]
            html += '<div class="text">' + "".join(paras) + "</div>"
        return (html + self._footer() + "</body></html>").encode()

    # --- routing ---------------------------------------------------------------
    def render(self, path: str) -> tuple[int, bytes, str]:
        if path == "/robots.txt":
            return 200, b"User-agent: Googlebot\nDisallow: /\n\nUser-agent: YandexBot\nDisallow: /\n", "text/plain"
        parts = [p for p in path.split("/") if p]
        rng = random.Random(f"{self.seed}:{path}")
        try:
            if not parts:
                body = "".join(f'<a href="/c/{t}/{s}/">Раздел {t}.{s}</a> ' for t in range(TOP) for s in range(SUB))
                return 200, self._page(rng, "Главная", "Бенч-магазин", body, "/"), "text/html"
            if len(parts) == 1 and parts[0].removesuffix(".html") in STATIC:
                name = parts[0].removesuffix(".html")
                return 200, self._page(rng, name, name, "", path), "text/html"
            if parts[0] == "c" and len(parts) == 2:
                t = int(parts[1])
                body = "".join(f'<a href="/c/{t}/{s}/">Раздел {t}.{s}</a> ' for s in range(SUB))
                return 200, self._page(rng, f"Категория {t}", f"Категория {t}", body, path), "text/html"
            if parts[0] == "c" and len(parts) in (3, 4):
                t, s = int(parts[1]), int(parts[2])
                k = int(parts[3].removeprefix("page-").removesuffix(".html")) if len(parts) == 4 else 1
                if not (t < TOP and s < SUB and 1 <= k <= self.list_pages):
                    raise ValueError
                first = (t * SUB + s) * self.per_sub + (k - 1) * PER_PAGE
                last = min(first + PER_PAGE, (t * SUB + s + 1) * self.per_sub, self.products)
                items = "".join(f'<a href="/p/{p}.html">Товар {p}</a> ' for p in range(first, last))
                nav = "".join(
                    f'<a href="/c/{t}/{s}/page-{j}.html">{j}</a> '
                    for j in range(max(1, k - 3), min(self.list_pages, k + 3) + 1)
                )
                return (
                    200,
                    self._page(rng, f"Раздел {t}.{s} — стр. {k}", f"Раздел {t}.{s}", items + nav, path),
                    "text/html",
                )
            if parts[0] == "p" and len(parts) == 2:
                pid = int(parts[1].removesuffix(".html"))
                if not 0 <= pid < self.products:
                    raise ValueError
                t, s = self._sub_of(pid)
                crumbs = f'<a href="/">Главная</a> / <a href="/c/{t}/">{t}</a> / <a href="/c/{t}/{s}/">{t}.{s}</a>'
                related = "".join(
                    f'<a href="/p/{rng.randrange(self.products)}.html">Похожий</a> ' for _ in range(RELATED)
                )
                return 200, self._page(rng, f"Товар {pid}", f"Товар {pid}", crumbs + related, path), "text/html"
        except ValueError:
            pass
        return 404, b"<html><body>not found</body></html>", "text/html"

    def all_paths(self):
        yield "/"
        yield from (f"/{s}.html" for s in STATIC)
        for t in range(TOP):
            yield f"/c/{t}/"
            for s in range(SUB):
                yield f"/c/{t}/{s}/"
                yield from (f"/c/{t}/{s}/page-{k}.html" for k in range(2, self.list_pages + 1))
        yield from (f"/p/{p}.html" for p in range(self.products))


# --- serve / build -----------------------------------------------------------------
def _worker(sock: socket.socket, pages: int, page_kb: int, seed: int) -> None:
    from aiohttp import web

    site = Site(pages, page_kb, seed)

    async def handle(request: web.Request) -> web.Response:
        # listing page 1 lives at /c/t/s/ ; /c/t/s/page-1.html is its duplicate -> 301 (a redirect to observe)
        if request.path.endswith("/page-1.html"):
            raise web.HTTPMovedPermanently(request.path.removesuffix("page-1.html"))
        status, body, ctype = site.render(request.path)
        return web.Response(status=status, body=body, content_type=ctype, charset="utf-8")

    app = web.Application()
    app.router.add_get("/{tail:.*}", handle)
    web.run_app(app, sock=sock, print=None, access_log=None)


def serve(args: argparse.Namespace) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(1024)
    sock.set_inheritable(True)
    site = Site(args.pages, args.page_kb, args.seed)
    print(
        f"PROTOTYPE bench site: {site.total} pages, ~{args.page_kb} KB each, http://127.0.0.1:{args.port}/ ({args.workers} workers)"
    )
    procs = [
        multiprocessing.Process(target=_worker, args=(sock, args.pages, args.page_kb, args.seed))
        for _ in range(args.workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


def build(args: argparse.Namespace) -> None:
    site, out = Site(args.pages, args.page_kb, args.seed), Path(args.out)
    n = 0
    for path in ["/robots.txt", *site.all_paths()]:
        _, body, _ = site.render(path)
        target = out / (path.lstrip("/") + ("index.html" if path.endswith("/") else ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        n += 1
        if path.startswith("/c/") and path.count("/") == 4:  # static stand-in for the server's 301
            dup = target.parent / "page-1.html"
            dup.write_text(f'<html><head><meta http-equiv="refresh" content="0; url={path}"></head></html>')
            n += 1
    print(f"built {n} files into {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "build"):
        p = sub.add_parser(name)
        p.add_argument("--pages", type=int, default=10_000)
        p.add_argument("--page-kb", type=int, default=60)
        p.add_argument("--seed", type=int, default=42)
    sub.choices["serve"].add_argument("--port", type=int, default=8765)
    sub.choices["serve"].add_argument("--workers", type=int, default=4)
    sub.choices["build"].add_argument("--out", default="./site-PROTOTYPE-wipe-me")
    args = ap.parse_args()
    serve(args) if args.cmd == "serve" else build(args)
