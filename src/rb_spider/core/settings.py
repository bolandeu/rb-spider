"""Crawl settings: one pydantic model, eight layers, and where every value came from.

Layers, each overriding the ones before it (docs/spec.md, section 4):

    default → global → project → profile (with `extends`) → --config file → env → flags → --set

Layers are merged here as flat `section.key` dicts rather than through pydantic-settings, because
`spider config show` must say which layer each value came from — provenance pydantic-settings
doesn't keep. A layer only contributes keys it sets explicitly, so a project file never shadows
the global one with defaults.

Every field has a `description=`: it is the help text of the key in `config show`, the
commented template of `profiles init`, the JSON Schema and docs/profiles.md.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .errors import InvalidArguments
from .version import CLI_NAME

_PACKAGE_NAME = __name__.split(".")[0]


# `crawl.user_agent` accepts one of these names instead of a full string.
USER_AGENT_PRESETS = {
    "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "googlebot-smartphone": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.6778.204 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "yandexbot": "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


class CrawlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["spider", "list"] = Field(
        "spider",
        description=(
            "spider — обход по ссылкам от стартового URL; list — только URL из списка (`spider crawl --list`) "
            "и шаги их редиректов, без перехода по ссылкам."
        ),
    )
    # --- how much
    max_urls: int | None = Field(
        None, ge=1, description="Остановиться после стольких URL; не задано — обойти весь сайт.", examples=[50000]
    )
    max_depth: int | None = Field(
        None,
        ge=0,
        description="Не идти глубже стольких кликов от стартового URL; не задано — без ограничения.",
        examples=[5],
    )
    max_links_per_page: int | None = Field(
        10000, ge=1, description="Брать с одной страницы не больше стольких ссылок; не задано — все."
    )
    max_url_length: int = Field(2000, ge=1, description="Не обходить URL длиннее стольких символов.")
    max_redirects: int = Field(
        20, ge=0, le=100, description="Проходить не больше стольких шагов одной цепочки редиректов (3xx)."
    )
    # --- what
    include: list[str] = Field(
        [],
        description="Обходить только URL, где находится хотя бы одно из этих регулярных выражений.",
        examples=[["/catalog/"]],
    )
    exclude: list[str] = Field(
        [],
        description="Не обходить URL, где находится любое из этих регулярных выражений (важнее include).",
        examples=[["\\?sort=", "/cart"]],
    )
    all_subdomains: bool = Field(
        False, description="Считать поддомены (blog.site.ru и т.п.) частью сайта и обходить их."
    )
    stay_in_start_folder: bool = Field(
        False, description="Обходить только внутри папки стартового URL (старт /blog/ — только /blog/…)."
    )
    check_outside_start_folder: bool = Field(
        True, description="С stay_in_start_folder: ссылки за пределами папки проверять (код ответа), но не обходить."
    )
    cdns: list[str] = Field(
        [],
        description="Домены CDN, которые считать частью сайта (и их поддомены): их URL обходятся как свои.",
        examples=[["cdn.example.net"]],
    )
    keep_fragments: bool = Field(False, description="Считать URL с разными #фрагментами разными страницами (SPA на #).")
    crawl_invalid_links: bool = Field(
        False,
        description="Обходить и синтаксически битые ссылки (без хоста, вида http:/site); иначе они отбрасываются.",
    )
    list_follow_canonicals: bool = Field(False, description="В режиме списка обходить и цели canonical.")
    follow_internal_nofollow: bool = Field(False, description="Обходить внутренние ссылки с rel=nofollow.")
    follow_external_nofollow: bool = Field(False, description="Проверять внешние ссылки с rel=nofollow.")
    content_exclude: list[str] = Field(
        ["nav", "footer"],
        description="CSS-селекторы блоков, которые не считаются текстом страницы (число слов, «Lorem ipsum»).",
    )
    # --- limits (Screaming Frog's Spider > Limits)
    max_page_size_kb: int | None = Field(
        None,
        ge=1,
        description="Страницы тяжелее стольких КБ не разбирать (код и размер записываются); не задано — все.",
    )
    max_urls_per_depth: int | None = Field(
        None, ge=1, description="Не больше стольких URL на каждом уровне глубины; не задано — без ограничения."
    )
    max_folder_depth: int | None = Field(
        None, ge=0, description="Не обходить URL глубже стольких папок в пути (/a/b/c — 3); не задано — любые."
    )
    max_query_params: int | None = Field(
        None, ge=0, description="Не обходить URL с большим числом GET-параметров; 0 — только без параметров."
    )
    max_urls_per_subdomain: int | None = Field(
        None, ge=1, description="С all_subdomains: не больше стольких URL с одного поддомена."
    )
    path_limits: list[tuple[str, int]] = Field(
        [],
        description="Лимиты по разделам: пары [регулярное выражение, максимум URL]; URL сверх лимита не обходятся.",
        examples=[[["/blog/", 1000], ["/tag/", 50]]],
    )
    # --- how fast
    concurrency: int = Field(20, ge=1, le=500, description="Сколько запросов к сайту выполняется одновременно.")
    max_rps: float | None = Field(
        None, gt=0, description="Не больше стольких запросов в секунду; не задано — без ограничения.", examples=[5]
    )
    timeout_s: float = Field(20, gt=0, description="Сколько секунд ждать ответа, прежде чем считать URL неответившим.")
    http_client: Literal["impit", "curl"] = Field(
        "impit",
        description=(
            "HTTP-клиент: impit — по умолчанию, самый быстрый; curl — запасной (curl-impersonate, "
            "`rb-spider[curl]`), если сайт плохо отвечает impit."
        ),
    )
    retries_5xx: int = Field(
        0, ge=0, le=10, description="Сколько раз повторять запрос, ответивший 5xx, прежде чем записать ошибку."
    )
    cookies: Literal["session", "none"] = Field(
        "session",
        description="Cookies: session — хранить в пределах обхода (как браузер); none — не хранить и не слать.",
    )
    assume_html: bool = Field(True, description="Ответ без Content-Type разбирать как HTML.")
    ca_bundle: str | None = Field(
        None,
        description=(
            "Свой корневой сертификат (PEM) — для MITM-прокси и корпоративных сетей; только с http_client = curl "
            "(impit свой CA не загружает — там только verify_tls = false)."
        ),
        examples=["/etc/ssl/company-root.pem"],
    )
    auth: Literal["none", "basic"] = Field(
        "none",
        description=(
            "HTTP-авторизация сайта: basic — заголовок Authorization к URL сайта (не к чужим); пароль — "
            "`spider auth login --provider site`."
        ),
    )
    auth_user: str | None = Field(None, description="Логин для auth = basic.", examples=["stage"])
    verify_tls: bool = Field(
        True,
        description=(
            "Проверять сертификат HTTPS; false — принимать и самоподписанные / просроченные (тестовые стенды)."
        ),
    )
    respect_hsts: bool = Field(
        True,
        description=(
            "Как браузер: после ответа с Strict-Transport-Security http-ссылки на тот же хост не скачивать, а "
            "записывать как 307 на https-адрес (HSTS Policy); false — скачивать и видеть настоящий редирект."
        ),
    )
    render: Literal["never", "always", "auto"] = Field(
        "never",
        description=(
            "JS-рендеринг: never — SEO-данные из HTML ответа сервера; always — HTML-страницы с кодом 200 ещё и "
            "открываются в браузере (Playwright, `rb-spider[render]`), данные — из DOM после выполнения JS; auto — "
            "первые render_auto_sample HTML-страниц рендерятся, и если JS ни на одной ничего не поменял (ссылки, "
            "текст, title, description, h1, canonical, robots), остальные читаются без браузера."
        ),
    )
    render_auto_sample: int = Field(
        20,
        ge=1,
        le=1000,
        description="Сколько первых HTML-страниц отрендерить при render = auto, чтобы решить, нужен ли JS.",
    )
    render_viewport: str = Field(
        "desktop",
        pattern=r"^(desktop|mobile|\d{2,5}x\d{2,5})$",
        description=(
            "Размер окна браузера при рендеринге (Window Size): desktop — 1366×768, mobile — 411×731 как у Googlebot "
            "Smartphone (сенсорный экран), или ШИРИНАxВЫСОТА, например 1920x1080."
        ),
    )
    render_console: bool = Field(
        True,
        description="Записывать ошибки и предупреждения консоли браузера при рендеринге (JavaScript Error Reporting).",
    )
    render_flatten_shadow_dom: bool = Field(
        True, description="Читать содержимое Shadow DOM веб-компонентов как часть страницы (Flatten Shadow DOM)."
    )
    render_flatten_iframes: bool = Field(
        True, description="Читать содержимое iframe как часть страницы, на которой он стоит (Flatten iframes)."
    )
    render_screenshots: bool = Field(
        False,
        description=(
            "Скриншот каждой отрендеренной страницы (первый экран, JPEG) — папка рядом с базой, путь в "
            "pages.screenshot и `spider url`; ~30–100 КБ на страницу."
        ),
    )
    render_images: bool = Field(
        False,
        description=(
            "Загружать картинки в браузере при рендеринге: медленнее, зато видны реальные и отображаемые размеры "
            "картинок (Image Details, «Images: Incorrectly Sized Images»); по умолчанию картинки не грузятся."
        ),
    )
    render_tabs: int = Field(
        4, ge=1, le=50, description="Сколько вкладок браузера открыто одновременно при рендеринге."
    )
    render_wait_ms: int = Field(
        0,
        ge=0,
        le=60000,
        description="Сколько миллисекунд ещё ждать скрипты после загрузки страницы (AJAX) при рендеринге.",
    )
    render_browser: str | None = Field(
        None,
        description=(
            "Путь к браузеру (Chromium / Chrome) для рендеринга; не задано — сборка Playwright, иначе самая "
            "свежая из кэша Playwright (ms-playwright), иначе установленный Google Chrome."
        ),
        examples=["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    )
    parse_workers: int | None = Field(
        None,
        ge=0,
        le=64,
        description=(
            "Сколько отдельных процессов разбирают HTML на больших обходах; 0 — всё в основном процессе; "
            "не задано — по числу ядер, не больше 4."
        ),
        examples=[2],
    )
    # --- as whom
    user_agent: str | None = Field(
        None,
        description=(
            "User-Agent запросов: своя строка или пресет — "
            + ", ".join(USER_AGENT_PRESETS)
            + "; не задано — как у обычного браузера (Firefox)."
        ),
        examples=["googlebot-smartphone"],
    )
    headers: dict[str, str] = Field(
        {}, description="Дополнительные заголовки каждого запроса.", examples=[{"Accept-Language": "ru"}]
    )
    robots: Literal["respect", "ignore", "report"] = Field(
        "respect",
        description=(
            "robots.txt: respect — запрещённое не скачивать (но показать в отчёте), с учётом Crawl-delay; "
            "ignore — не читать; report — скачивать всё, но отмечать запрещённое."
        ),
    )
    robots_custom: str | None = Field(
        None,
        description="Свой robots.txt для сайта вместо настоящего — проверить правки до выкладки (текст файла).",
        examples=["User-agent: *\nDisallow: /cart"],
    )
    robots_show_internal_blocked: bool = Field(
        True, description="Записывать в отчёт URL сайта, запрещённые robots.txt."
    )
    robots_show_external_blocked: bool = Field(
        True, description="Записывать в отчёт чужие URL, запрещённые их robots.txt."
    )
    robots_user_agent: str | None = Field(
        None,
        description="От чьего имени читать robots.txt; не задано — от User-Agent запросов.",
        examples=["Googlebot"],
    )
    proxy_urls: list[str] = Field(
        [],
        description=(
            "Прокси, чередуются по запросам. Пароль не пишите в файл: `{password}` в адресе заменится секретом из "
            "`spider auth login --provider proxy`."
        ),
        examples=[["http://user:{password}@proxy.example:8000"]],
    )
    # --- what to keep
    store_html: bool = Field(
        False, description="Сохранять HTML страниц (сжатым, в отдельный файл рядом с базой); иначе только md5."
    )

    @field_validator("path_limits")
    @classmethod
    def _valid_path_limits(cls, limits: list[tuple[str, int]]) -> list[tuple[str, int]]:
        for pattern, _ in limits:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc
        return limits

    @field_validator("include", "exclude")
    @classmethod
    def _valid_regexes(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc
        return patterns

    @property
    def resolved_user_agent(self) -> str | None:
        """The full User-Agent string: a preset name expanded, None for the browser default."""
        return USER_AGENT_PRESETS.get(self.user_agent or "", self.user_agent)


class FollowStore(BaseModel):
    """One kind of link: whether to follow it (crawl / check the target) and whether to keep the link rows."""

    model_config = ConfigDict(extra="forbid")

    follow: bool = Field(True, description="Переходить по таким ссылкам (обходить или проверять цель).")
    store: bool = Field(True, description="Хранить сами ссылки в базе (для `spider links` и проверок ссылок).")


class CollectSettings(BaseModel):
    """What to follow and what to keep — Screaming Frog's Spider > Crawl checkboxes (Crawl / Store)."""

    model_config = ConfigDict(extra="forbid")

    internal_links: FollowStore = Field(default_factory=FollowStore, description="Внутренние ссылки <a href>.")
    external_links: FollowStore = Field(
        default_factory=FollowStore, description="Внешние ссылки: follow — проверить код ответа (без обхода)."
    )
    canonicals: FollowStore = Field(
        default_factory=FollowStore, description="Canonical: follow — обходить цели canonical."
    )
    meta_refresh: FollowStore = Field(
        default_factory=FollowStore, description="Meta / HTTP Refresh: follow — обходить цели refresh."
    )
    images: FollowStore = Field(
        default_factory=FollowStore, description="Картинки <img>: follow — проверить код ответа и вес."
    )
    hreflang: FollowStore = Field(
        default_factory=FollowStore,
        description="Hreflang (<link rel=alternate hreflang>, заголовок Link): follow — обходить альтернативные URL.",
    )
    pagination: FollowStore = Field(
        default_factory=FollowStore,
        description="Пагинация <link rel=next / prev> (и заголовок Link): follow — обходить соседние страницы.",
    )
    mobile_alternate: FollowStore = Field(
        default_factory=FollowStore,
        description="Мобильная версия <link rel=alternate media=…>: follow — обходить её страницы.",
    )
    link_path: bool = Field(
        False,
        description="Хранить у каждой ссылки путь её предков (/nav.menu/…) — для разбора зон; ~40 байт на ссылку.",
    )
    uncrawlable_links: bool = Field(
        False,
        description="Хранить и «ссылки», по которым не перейти (javascript:, href не у <a>, onclick) — видны в `spider links`.",
    )
    html_validation: bool = Field(
        True, description="Проверять структуру HTML по исходному коду: <head> / <body>, порядок, элементы в <head>."
    )
    images_srcset: bool = Field(False, description="Брать картинки и из атрибута srcset, а не только src.")
    structured_data: list[Literal["json-ld", "microdata", "rdfa"]] = Field(
        [],
        description=(
            "Какую микроразметку извлекать и проверять (Schema.org, расширенные результаты Google): json-ld, "
            "microdata, rdfa; пусто — не извлекать. Microdata и RDFa — extra `rb-spider[structured]`."
        ),
        examples=[["json-ld", "microdata"]],
    )
    near_duplicates: bool = Field(
        False,
        description=(
            "Считать подписи MinHash текста страниц — для проверки «Content: Near Duplicates» (extra "
            "`rb-spider[near]`; ~0,7 КБ на страницу)."
        ),
    )
    css: FollowStore = Field(default_factory=FollowStore, description="Стили <link rel=stylesheet>.")
    js: FollowStore = Field(default_factory=FollowStore, description="Скрипты <script src>.")
    media: FollowStore = Field(default_factory=FollowStore, description="Видео и аудио <video>, <audio>, <source>.")
    iframes: FollowStore = Field(default_factory=FollowStore, description="Встроенные фреймы <iframe>.")


class RewriteSettings(BaseModel):
    """URL Rewriting: how discovered URLs are changed before they are stored and crawled (Screaming Frog's
    Configuration > URL Rewriting). The start URL and the URLs of a list crawl stay as given."""

    model_config = ConfigDict(extra="forbid")

    remove_params: list[str] = Field(
        [],
        description="Удалять из найденных URL эти GET-параметры (точное имя, с учётом регистра).",
        examples=[["sid", "utm_source", "utm_medium"]],
    )
    regex: list[tuple[str, str]] = Field(
        [],
        description=(
            "Замены по регулярным выражениям, по порядку: пары [выражение, замена]; группы в замене — \\1, \\2."
        ),
        examples=[[["^http://", "https://"]]],
    )
    lowercase: bool = Field(False, description="Переводить найденные URL в нижний регистр целиком.")
    percent_encoding: Literal["keep", "upper", "lower"] = Field(
        "keep",
        description="Регистр шестнадцатеричных цифр в %-кодировании (%D0 или %d0): keep — как на странице.",
    )

    @field_validator("regex")
    @classmethod
    def _valid_regexes(cls, rules: list[tuple[str, str]]) -> list[tuple[str, str]]:
        for pattern, _ in rules:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc
        return rules


class SitemapSettings(BaseModel):
    """XML sitemaps: Screaming Frog's Crawl Linked XML Sitemaps (Spider > Crawl), through rb-sitemap-xml."""

    model_config = ConfigDict(extra="forbid")

    crawl: bool = Field(
        False,
        description=(
            "Читать XML sitemap сайта (extra `rb-spider[sitemaps]`): проверки Sitemaps, `spider sitemaps`. "
            "Файлы качаются без прокси, с User-Agent и timeout обхода."
        ),
    )
    discover: bool = Field(
        True, description="Искать sitemap сам: строки Sitemap: в robots.txt, затем /sitemap.xml и т.п."
    )
    urls: list[str] = Field(
        [],
        description="Адреса sitemap (или индексов) вдобавок к найденным.",
        examples=[["https://example.com/sitemap.xml"]],
    )
    follow: bool = Field(
        True, description="Обходить URL из sitemap, даже если на них нет ссылок (иначе — только сравнивать)."
    )


class CustomSearch(BaseModel):
    """One Custom Search rule: how many times a text or a regular expression occurs on each page."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Имя поиска — так он называется в `spider custom`.")
    query: str = Field(description="Что искать: текст или регулярное выражение (regex = true).")
    regex: bool = Field(False, description="query — регулярное выражение Python.")
    case_sensitive: bool = Field(False, description="Учитывать регистр.")
    scope: Literal["html", "text", "element"] = Field(
        "html",
        description="Где искать: html — исходный код; text — текст страницы; element — текст элементов selector.",
    )
    selector: str | None = Field(None, description="CSS-селектор для scope = element.")

    @model_validator(mode="after")
    def _valid(self) -> CustomSearch:
        if not self.query:
            raise ValueError("query is empty")
        if self.regex:
            _check_regex(self.query)
        if self.scope == "element" and not self.selector:
            raise ValueError("scope = element needs a selector")
        return self


class CustomExtract(BaseModel):
    """One Custom Extraction rule: values taken from each page into `spider custom`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Имя извлечения — так оно называется в `spider custom`.")
    kind: Literal["css", "xpath", "regex"] = Field(
        "css",
        description="css — CSS-селектор; xpath — XPath (extra `rb-spider[xpath]`); regex — группа 1 или всё совпадение.",
    )
    query: str = Field(description="Селектор, XPath или регулярное выражение.")
    output: str = Field(
        "text",
        description="Что брать у элемента: text, html (элемент целиком), inner_html или имя атрибута (href, content…).",
    )
    limit: int = Field(1, ge=1, le=100, description="Сколько значений брать со страницы.")

    @model_validator(mode="after")
    def _valid(self) -> CustomExtract:
        if self.kind == "regex":
            _check_regex(self.query)
        return self


def _check_regex(pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc


DEFAULT_LINK_POSITIONS = [["nav", "nav"], ["menu", "nav"], ["header", "header"], ["footer", "footer"],
                          ["aside", "sidebar"], ["sidebar", "sidebar"]]  # fmt: skip


class CustomSettings(BaseModel):
    """Custom Search, Custom Extraction and link positions (Screaming Frog's Configuration > Custom)."""

    model_config = ConfigDict(extra="forbid")

    search: list[CustomSearch] = Field(
        [],
        description="Поиски по страницам: [[custom.search]] с name, query, regex, scope (html / text / element).",
        examples=[[{"name": "GTM", "query": "googletagmanager.com"}]],
    )
    extract: list[CustomExtract] = Field(
        [],
        description="Извлечения: [[custom.extract]] с name, kind (css / xpath / regex), query, output, limit.",
        examples=[[{"name": "price", "query": ".price", "output": "text"}]],
    )
    link_positions: list[tuple[str, str]] = Field(
        [(word, zone) for word, zone in DEFAULT_LINK_POSITIONS],
        description=(
            "Зоны ссылок: пары [слово пути, зона] по порядку — слово класса, id или тега предка ссылки; ни одно не "
            "подошло — content."
        ),
    )


COMPARE_FIELDS = [
    "indexability", "status_code", "title", "meta_description", "h1", "h2", "canonical", "directives", "word_count",
    "content", "depth", "inlinks", "unique_inlinks", "internal_outlinks", "unique_outlinks", "external_outlinks",
    "structured_data_types",
]  # fmt: skip


class UrlMapping(BaseModel):
    """One URL Mapping rule of `spider compare`."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(description="Регулярное выражение (Python) по URL прежнего обхода.")
    replace: str = Field(description="На что заменить совпадение (\\1 — группа из pattern).")

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"not a regular expression: {exc}") from exc
        return pattern


class CompareSettings(BaseModel):
    """What `spider compare` checks for changes (Screaming Frog's Config > Compare, Change Detection)."""

    model_config = ConfigDict(extra="forbid")

    fields: list[str] = Field(
        list(COMPARE_FIELDS),
        description="Поля Change Detection: " + ", ".join(COMPARE_FIELDS) + " (content — HTML изменился, по md5).",
    )
    url_mapping: list[UrlMapping] = Field(
        [],
        description=(
            "URL Mapping: правила «регулярное выражение → замена» для URL прежнего обхода, чтобы сравнить разные "
            "адреса одних страниц — staging против production, переезд на другой домен или HTTPS, новая структура "
            "URL. Применяются по порядку."
        ),
        examples=[[{"pattern": "^https://staging\\.example\\.com", "replace": "https://example.com"}]],
    )

    @field_validator("fields")
    @classmethod
    def _known(cls, fields: list[str]) -> list[str]:
        unknown = [f for f in fields if f not in COMPARE_FIELDS]
        if unknown:
            raise ValueError(f"unknown fields {unknown}: one of {', '.join(COMPARE_FIELDS)}")
        return fields


EXPORT_DATASETS = ["pages", "links", "issues", "queued", "headers", "cookies", "source", "text", "duplicates",
                   "custom", "sitemap-urls", "javascript", "rendered-source", "screenshots", "lighthouse"]  # fmt: skip


class ExportSettings(BaseModel):
    """Multi-Export presets: `spider export --preset NAME` writes several datasets in one call."""

    model_config = ConfigDict(extra="forbid")

    presets: dict[str, list[str]] = Field(
        {
            "audit": ["pages", "issues", "links"],
            "links": ["links", "links:links_no_anchor_text", "links:links_internal_nofollow_outlinks",
                      "links:internal_client_error"],
            "full": list(EXPORT_DATASETS),
        },
        description=(
            "Пресеты выгрузки: имя → список наборов (" + ", ".join(EXPORT_DATASETS) + "); `набор:код` — только "
            "находки / ссылки / URL одной проверки, например `issues:page_title_missing`, `links:links_no_anchor_text`."
        ),
    )  # fmt: skip


class ThresholdSettings(BaseModel):
    """Limits the issue rules compare against. Changing them needs `spider analyze`, not a new crawl."""

    model_config = ConfigDict(extra="forbid")

    redirect_chain_hops: int = Field(
        2, ge=2, description="Со скольких прыжков редирект считается цепочкой (Internal Redirect Chain)."
    )
    title_max_chars: int = Field(60, ge=1, description="Title длиннее — «Page Titles: Over … Characters».")
    title_min_chars: int = Field(30, ge=1, description="Title короче — «Page Titles: Below … Characters».")
    description_max_chars: int = Field(
        155, ge=1, description="Meta description длиннее — «Meta Description: Over … Characters»."
    )
    description_min_chars: int = Field(
        70, ge=1, description="Meta description короче — «Meta Description: Below … Characters»."
    )
    title_max_px: int = Field(
        561, ge=1, description="Title шире стольких пикселей в выдаче — «Page Titles: Over … Pixels»."
    )
    title_min_px: int = Field(200, ge=1, description="Title уже — «Page Titles: Below … Pixels».")
    description_max_px: int = Field(
        985,
        ge=1,
        description="Meta description шире (в сумме по строкам сниппета) — «Meta Description: Over … Pixels».",
    )
    description_min_px: int = Field(400, ge=1, description="Meta description уже — «Meta Description: Below … Pixels».")
    serp_title_font_px: float = Field(
        20, gt=0, description="Кегль title в выдаче Google (Arial), по нему считаются пиксели."
    )
    serp_description_font_px: float = Field(
        14, gt=0, description="Кегль сниппета в выдаче Google (Arial), по нему считаются пиксели description."
    )
    h1_max_chars: int = Field(70, ge=1, description="H1 длиннее — «H1: Over … Characters».")
    h2_max_chars: int = Field(70, ge=1, description="H2 длиннее — «H2: Over … Characters».")
    low_content_words: int = Field(
        200, ge=1, description="Меньше слов в видимом тексте — «Content: Low Content Pages»."
    )
    image_kb: int = Field(100, ge=1, description="Картинка тяжелее стольких КБ — «Images: Over … KB».")
    alt_max_chars: int = Field(100, ge=1, description="Alt длиннее — «Images: Alt Text Over … Characters».")
    crawl_depth: int = Field(4, ge=1, description="Страницы на такой глубине и глубже — «Links: High Crawl Depth».")
    internal_outlinks: int = Field(
        1000, ge=1, description="Больше внутренних follow-ссылок — «Links: High Internal Outlinks»."
    )
    external_outlinks: int = Field(
        10, ge=1, description="Больше внешних follow-ссылок — «Links: High External Outlinks»."
    )
    non_descriptive_anchors: list[str] = Field(
        ["click here", "here", "read more", "more", "learn more", "link",
         "подробнее", "читать далее", "далее", "здесь", "тут", "ссылка", "перейти", "узнать больше"],
        description="Анкоры, ничего не говорящие о цели (без учёта регистра) — «Links: Non-Descriptive Anchor Text».",
    )  # fmt: skip
    url_max_chars: int = Field(115, ge=1, description="URL длиннее — «URL: Over … Characters».")
    duplicates_indexable_only: bool = Field(
        True, description="Искать дубли (точные, почти-дубли, title и т.д.) только среди индексируемых страниц."
    )
    near_duplicate_similarity: int = Field(
        90, ge=50, le=100, description="С какого сходства текста (%) страницы — почти-дубли (MinHash)."
    )
    readability_difficult: float = Field(
        50, description="Индекс Флеша ниже — «Content: Readability Difficult» (для русского — формула Оборневой)."
    )
    readability_very_difficult: float = Field(
        30, description="Индекс Флеша ниже — «Content: Readability Very Difficult»."
    )
    readability_min_words: int = Field(
        100, ge=1, description="Читаемость оценивается у страниц хотя бы со стольких слов текста."
    )
    soft_404_patterns: list[str] = Field(
        [r"\b404\b", r"not found", r"page (does not|doesn't|no longer) exist", r"не найден", r"не существует",
         r"нет такой страницы", r"страница удалена"],
        description=(
            "Регулярные выражения (без учёта регистра) по title и H1 страницы с кодом 200: совпало — "
            "«Content: Soft 404 Pages»."
        ),
    )  # fmt: skip
    document_max_mb: float = Field(
        2,
        gt=0,
        description="HTML-страница больше стольких МБ — «Validation: HTML Document Over 2MB» (Googlebot читает 2 МБ).",
    )
    resource_max_mb: float = Field(
        2, gt=0, description="JS / CSS больше стольких МБ — «Validation: Resource Over 2MB»."
    )
    image_oversize_ratio: float = Field(
        2,
        ge=1,
        description=(
            "Картинка шире или выше, чем показана на странице, больше чем во столько раз — «Images: Incorrectly Sized "
            "Images» (2 — запас на экраны высокой плотности)."
        ),
    )
    js_content_min_words: int = Field(
        10,
        ge=1,
        description="После JS на странице хотя бы столько новых слов — «JavaScript: Contains JavaScript Content».",
    )
    sitemap_max_urls: int = Field(
        50000, ge=1, description="Больше URL в одном файле sitemap — «Sitemaps: Over 50k URLs»."
    )
    sitemap_max_mb: float = Field(
        50, gt=0, description="Файл sitemap больше стольких МБ (без сжатия) — «Sitemaps: Over 50mb»."
    )
    issues_indexable_only: bool = Field(
        False,
        description=(
            "Проверки контента (title, description, H1, H2, Content…) только для индексируемых страниц — "
            "Ignore Non-Indexable URLs for Issues."
        ),
    )
    self_refresh_non_indexable: bool = Field(
        True, description="Страница с meta / HTTP Refresh на саму себя — неиндексируемая (Redirected)."
    )
    ignore_paginated_duplicates: bool = Field(
        True,
        description=(
            "Не считать дублями title / description / H1 / H2 страниц пагинации 2+ (с rel=prev): у страниц "
            "одного списка они обычно одинаковы."
        ),
    )
    internal_search: list[str] = Field(
        [r"[?&](q|s|query|search|text|keyword|keywords)=", r"/(search|poisk|find)(/|$|\?)"],
        description=(
            "Регулярные выражения (без учёта регистра) по пути и параметрам URL: совпало — страница внутреннего "
            "поиска, «URL: Internal Search»."
        ),
    )

    @field_validator("internal_search", "soft_404_patterns")
    @classmethod
    def _valid_regexes(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc
        return patterns


class LighthouseSettings(BaseModel):
    """`spider lighthouse`: page speed and mobile audits by Lighthouse run on this machine (Node.js + npm lighthouse)."""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(
        "lighthouse",
        description=(
            "Как запускать Lighthouse: команда из PATH (`npm install -g lighthouse`) или, например, "
            '"npx --yes lighthouse" — без установки.'
        ),
    )
    strategy: Literal["mobile", "desktop"] = Field(
        "mobile", description="Мобильный (как Googlebot Smartphone) или десктопный замер; mobile — ещё и замеры Mobile."
    )
    per_template: int = Field(
        1,
        ge=1,
        le=20,
        description=(
            "Сколько страниц брать на шаблон, когда URL не заданы: шаблон — папка и глубина пути (все /catalog/x/y — "
            "один), страницы — с наибольшим числом входящих ссылок; главная — всегда."
        ),
    )
    max_pages: int = Field(20, ge=1, le=10000, description="Не больше стольких страниц выборки за запуск.")
    timeout_s: int = Field(120, ge=10, le=900, description="Сколько секунд ждать Lighthouse на одной странице.")
    chrome: str | None = Field(
        None,
        description=(
            "Путь к Chrome / Chromium для Lighthouse; не задано — crawl.render_browser, иначе Chromium из кэша "
            "Playwright, иначе установленный Chrome."
        ),
    )


class Settings(BaseModel):
    """Everything a crawl can be configured with. Sections are TOML tables: `[crawl]`, `[thresholds]`."""

    model_config = ConfigDict(extra="forbid")

    crawl: CrawlSettings = Field(default_factory=CrawlSettings, description="Как обходить сайт.")
    collect: CollectSettings = Field(
        default_factory=CollectSettings, description="Что обходить и что хранить: ссылки, canonical, refresh."
    )
    sitemaps: SitemapSettings = Field(default_factory=SitemapSettings, description="XML sitemap: чтение и проверки.")
    export: ExportSettings = Field(default_factory=ExportSettings, description="Пресеты выгрузки (Multi-Export).")
    compare: CompareSettings = Field(
        default_factory=CompareSettings, description="Сравнение обходов: поля Change Detection."
    )
    custom: CustomSettings = Field(
        default_factory=CustomSettings,
        description="Свои поиски, извлечения и зоны ссылок (Custom Search / Extraction).",
    )
    rewrite: RewriteSettings = Field(
        default_factory=RewriteSettings, description="Переписывание найденных URL: параметры, замены, регистр."
    )
    lighthouse: LighthouseSettings = Field(
        default_factory=LighthouseSettings,
        description="Скорость и мобильные проверки Lighthouse (`spider lighthouse`).",
    )
    thresholds: ThresholdSettings = Field(
        default_factory=ThresholdSettings, description="Пороги проверок; пересчёт без обхода — `spider analyze`."
    )


class ProfileFile(Settings):
    """A profile / `--config` file: settings plus its own metadata."""

    description: str | None = Field(None, description="Для чего профиль — видно в `spider profiles list`.")
    extends: str | None = Field(None, description="Профиль, от которого наследуются незаданные ключи.")


SECTIONS = tuple(Settings.model_fields)
_ENV_PREFIX = f"{CLI_NAME.upper()}_"


# --- flat dotted-key dicts --------------------------------------------------------------


def flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{dotted}."))
        else:
            flat[dotted] = value
    return flat


def unflatten(flat: dict[str, Any]) -> dict:
    nested: dict = {}
    for dotted, value in flat.items():
        *parents, leaf = dotted.split(".")
        node = nested
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return nested


def _leaf_fields(model: type[BaseModel], prefix: str = "") -> list[tuple[str, Any]]:
    """(dotted key, field) for every leaf setting; nested models (`collect.internal_links`) are walked into."""
    rows = []
    for key, field in model.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            rows += _leaf_fields(annotation, f"{prefix}{key}.")
        else:
            rows.append((f"{prefix}{key}", field))
    return rows


def settings_keys() -> list[str]:
    """Every settable key, dotted: `crawl.max_urls`, `collect.internal_links.follow`."""
    return [dotted for dotted, _ in _leaf_fields(Settings)]


# --- layer sources ----------------------------------------------------------------------


def _read_toml(path: Path, label: str) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise InvalidArguments(f"{label}: not valid TOML ({exc}).") from exc


def _settings_part(data: dict) -> dict:
    return {k: v for k, v in data.items() if k in SECTIONS}


def global_config_path() -> Path:
    return Path(platformdirs.user_config_dir(CLI_NAME, appauthor=False)) / "config.toml"


def builtin_profiles() -> dict[str, Path]:
    folder = resources.files(f"{_PACKAGE_NAME}.data").joinpath("profiles")
    return {Path(p.name).stem: Path(str(p)) for p in folder.iterdir() if p.name.endswith(".toml")}


def project_profiles(project_root: Path | None) -> dict[str, Path]:
    if project_root is None:
        return {}
    folder = project_root / f".{CLI_NAME}" / "profiles"
    return {p.stem: p for p in sorted(folder.glob("*.toml"))} if folder.is_dir() else {}


def available_profiles(project_root: Path | None) -> dict[str, tuple[str, Path]]:
    """name -> (where, path); a project profile shadows a built-in one of the same name."""
    found = {name: ("builtin", path) for name, path in builtin_profiles().items()}
    found.update({name: ("project", path) for name, path in project_profiles(project_root).items()})
    return found


def load_profile_file(path: Path, label: str) -> ProfileFile:
    try:
        return ProfileFile.model_validate(_read_toml(path, label))
    except ValidationError as exc:
        raise InvalidArguments(_explain(exc, label)) from exc


def profile_layers(name: str, project_root: Path | None) -> list[tuple[str, dict]]:
    """The profile and its `extends` ancestors as layers, most general first."""
    profiles = available_profiles(project_root)
    chain: list[tuple[str, dict]] = []
    seen: list[str] = []
    current: str | None = name
    while current is not None:
        if current in seen:
            raise InvalidArguments(f"Profile inheritance loops: {' → '.join([*seen, current])}.")
        if current not in profiles:
            known = ", ".join(sorted(profiles))
            raise InvalidArguments(f"No profile '{current}'. Available: {known} (`spider profiles list`).")
        seen.append(current)
        _, path = profiles[current]
        profile = load_profile_file(path, f"profile '{current}' ({path})")  # validates keys and types
        chain.append((f"profile:{current}", _settings_part(_read_toml(path, str(path)))))
        current = profile.extends
    return list(reversed(chain))


def env_layer(environ: dict[str, str]) -> dict:
    """`SPIDER_CRAWL__MAX_URLS=500` → {"crawl": {"max_urls": "500"}}. Only double-underscore names count,
    so `SPIDER_DB_PATH` and credential variables (`SPIDER_<PROVIDER>_<FIELD>`) are left alone."""
    flat = {}
    for name, value in environ.items():
        if name.startswith(_ENV_PREFIX) and "__" in name:
            section, _, key = name.removeprefix(_ENV_PREFIX).lower().partition("__")
            flat[f"{section}.{key}"] = parse_value(value)
    return unflatten(flat)


def parse_value(raw: str) -> Any:
    """A TOML literal when it is one (`1000`, `true`, `["a"]`, `"x"`), otherwise the plain string."""
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def set_layer(assignments: list[str]) -> dict:
    flat = {}
    for item in assignments:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise InvalidArguments(f"--set expects key=value, got '{item}'.")
        flat[key.strip()] = parse_value(value.strip())
    return unflatten(flat)


# --- resolution -------------------------------------------------------------------------


@dataclass
class Resolved:
    settings: Settings
    sources: dict[str, str]  # section.key -> layer label ("default", "project", "profile:fast", "set", ...)


def _explain(exc: ValidationError, where: str, sources: dict[str, str] | None = None) -> str:
    problems = []
    for error in exc.errors():
        key = ".".join(str(part) for part in error["loc"])
        origin = f" (from {sources[key]})" if sources and key in sources else ""
        problems.append(f"{key}: {error['msg']}{origin}")
    return f"{where}: " + "; ".join(problems) + ". Valid keys: `spider config schema`."


def resolve(
    project_root: Path | None,
    *,
    project_data: dict | None = None,
    profile: str | None = None,
    config_file: Path | None = None,
    flags: dict[str, Any] | None = None,
    assignments: list[str] | None = None,
    environ: dict[str, str] | None = None,
) -> Resolved:
    """Merge all layers into validated Settings, remembering the layer each value came from."""
    layers: list[tuple[str, dict]] = []
    global_path = global_config_path()
    if global_path.is_file():
        layers.append(("global", _settings_part(_read_toml(global_path, f"global config ({global_path})"))))
    if project_data:
        layers.append(("project", _settings_part(project_data)))
    if profile:
        layers.extend(profile_layers(profile, project_root))
    if config_file:
        if not config_file.is_file():
            raise InvalidArguments(f"--config: no file '{config_file}'.")
        layers.append((f"file:{config_file}", _settings_part(_read_toml(config_file, f"--config {config_file}"))))
    layers.append(("env", env_layer(dict(os.environ) if environ is None else environ)))
    layers.append(("flag", unflatten({k: v for k, v in (flags or {}).items() if v is not None})))
    layers.append(("set", set_layer(assignments or [])))

    merged: dict[str, Any] = {}
    sources = dict.fromkeys(settings_keys(), "default")
    for label, data in layers:
        for key, value in flatten(data).items():
            merged[key] = value
            sources[key] = label
    try:
        settings = Settings.model_validate(unflatten(merged))
    except ValidationError as exc:
        raise InvalidArguments(_explain(exc, "Invalid settings", sources)) from exc
    return Resolved(settings, sources)


# --- docs -------------------------------------------------------------------------------


def _field_rows() -> list[tuple[str, Any]]:
    return _leaf_fields(Settings)


def _table_description(table: str) -> str | None:
    """The description of a nested table (`collect.internal_links`) — its field in the parent model."""
    model: Any = Settings
    field = None
    for part in table.split("."):
        field = model.model_fields[part]
        model = field.annotation
    return field.description if field else None


def _toml_literal(value: Any) -> str:
    """`value` as a one-line TOML literal (`true`, `"x"`, `["a", "b"]`, `{ "k" = "v" }`) for templates and docs."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid TOML basic string
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{json.dumps(k, ensure_ascii=False)} = {_toml_literal(v)}" for k, v in value.items())
        return "{ " + pairs + " }" if pairs else "{}"
    return str(value)


def profile_template(name: str, extends: str | None) -> str:
    """A profile file with every key commented out, described, and set to its default/example."""
    lines = [
        f"# Профиль spider «{name}». Раскомментируйте нужные ключи.",
        "# Справочник ключей — docs/profiles.md; проверить файл — `spider config validate <файл>`.",
        "",
        'description = ""',
        f'extends = "{extends}"' if extends else '# extends = "default"',
    ]
    current = None
    for dotted, field in _field_rows():
        table, key = dotted.rsplit(".", 1)
        if table != current:
            lines += ["", f"# {_table_description(table)}", f"[{table}]"]
            current = table
        value = field.default if field.default is not None else (field.examples or [None])[0]
        lines.append(f"# {field.description}")
        lines.append(f"# {key} = {_toml_literal(value)}" if value is not None else f"# {key} =")
    return "\n".join(lines) + "\n"


def reference_markdown() -> str:
    """The key reference table for docs/profiles.md."""
    lines = ["| Ключ | Тип | По умолчанию | Описание |", "| --- | --- | --- | --- |"]
    for dotted, field in _field_rows():
        kind = str(field.annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")
        kind = kind.replace(" | ", r" \| ")  # a bare pipe would split the markdown table cell
        default = "—" if field.default is None else f"`{_toml_literal(field.default)}`"
        lines.append(f"| `{dotted}` | `{kind}` | {default} | {field.description} |")
    return "\n".join(lines) + "\n"


def profiles_markdown() -> str:
    """The built-in profiles (recipes included) for docs/profiles.md: each one's description and file."""
    names = sorted(builtin_profiles(), key=lambda name: (name != "default", name))
    blocks = []
    for name in names:
        text = builtin_profiles()[name].read_text(encoding="utf-8").strip()
        profile = ProfileFile.model_validate(tomllib.loads(text))
        blocks.append(f"### `{name}`\n\n{profile.description}\n\n```toml\n{text}\n```\n")
    return "\n".join(blocks)
