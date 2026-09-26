# rb-spider — спецификация

SEO-краулер для технического аудита сайтов, функциональный аналог [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/).
Python-библиотека `rb_spider` + CLI `spider`. Пользователь — один человек из терминала и ИИ-агенты (интерфейс команд рассчитан на обоих).

Полный перечень функций и проверок по волнам — в [features.md](features.md).

---

## 1. Стек и выбор библиотек

| Слой | Выбор | Почему | Отвергнуто |
|---|---|---|---|
| Движок обхода | **Crawlee for Python** (`HttpCrawler`, версия пинится) | Очередь, автомасштабирование, прокси (ротация, tiered), robots.txt, возобновление, Playwright — из коробки. Apache-2.0, активно развивается (1.10.x, 09.2026) | **Scrapy** — решение пользователя; свой движок на httpx — пришлось бы писать очередь/прокси/рендеринг самим |
| HTTP-клиент | **ImpitHttpClient** (дефолт Crawlee, Rust, HTTP/2–3, браузерный отпечаток) | Самый быстрый из доступных в Crawlee | httpx — медленнее; `CurlImpersonateHttpClient` — оставлен как переключаемый запасной (`http.client = "curl"`) |
| Парсинг HTML | **selectolax** (Lexbor) | В 3–4× быстрее lxml. Извлечение SEO-данных — наш код, не привязан к движку: одинаково работает по сырому и отрендеренному HTML | `ParselCrawler` / BeautifulSoup — медленнее; lxml/parsel — только для пользовательских XPath (v2) |
| JS-рендеринг | **Playwright** через `PlaywrightCrawler` | Встроен в Crawlee | `AdaptivePlaywrightCrawler` в MVP — непредсказуем для аудита (ML-предиктор по похожести URL); возможен в v2 как `render=auto` |
| Хранилище результатов | **Своя схема на SQLAlchemy 2 + Alembic** | Нужны нормальные таблицы и связи (граф ссылок, отчёты SQL-ом); один код для SQLite / Postgres / MySQL | Датасет Crawlee — JSON-блобы без колонок, SQL-запросов нет |
| Очередь Crawlee | **SqlStorageClient** в отдельном SQLite-файле, за своим интерфейсом | Переживает 100k+ URL и перезапуск | Файловая очередь (держит до 100k запросов в памяти) — запасной вариант при проблемах экспериментального SQL-клиента |
| Структурированные данные (v2) | extruct | JSON-LD, microdata, RDFa, OpenGraph | — |
| Почти-дубли (v2) | datasketch (MinHash/LSH) | Поддерживается | пакет `simhash` — заброшен |
| robots.txt | protego (через Crawlee) | Уже внутри Crawlee | reppy — заброшен |
| Sitemap | соседний пакет **rb-sitemap-xml** | Свой, развиваем | ultimate-sitemap-parser — GPL-3.0 |
| Конфиг | **pydantic-settings** | Слои TOML/env из коробки, JSON Schema | — |
| CLI | Архитектура скилла `cli-builder`: Python 3.12+, uv, Typer, конфиг проекта, секреты в keychain, вывод человек/`--json`, ИИ-понятные ошибки, коды выхода | Единая архитектура всех CLI пользователя | — |

Готовые SEO-краулеры (advertools — на Scrapy, SEOnaut — Go, LibreCrawl, pyseoanalyzer) как зависимость не берём; advertools и SEOnaut — источник списков колонок и проверок.

---

## 2. Модель данных

- Иерархия: **project** (сайт) → **crawl** (один запуск) → строки данных с `crawl_id`.
- Таблицы (ориентир): `projects`, `crawls` (статус, итоговый конфиг-снимок), `pages`, `links`, `redirects`, `images`, `hreflang`, `issues`, `url_metrics` (для обогатителей), `html_store` (опционально).
- Итоговый (resolved) конфиг каждого обхода сохраняется в `crawls` — чтобы объяснять разницу между обходами.
- Проверки (issues): в основном **SQL-представления** поверх таблиц обхода; сложные — Python. Пороги (длина title и т.п.) — из конфига. Проверка, которой нужны невыключенные данные, получает статус «не проверялось», а не «ок».

### Большие обходы (цель — 100k URL на Mac без роста ОЗУ)

| Что растёт | Мера |
|---|---|
| Очередь и виденные URL | SQL-очередь на диске |
| Граф ссылок, данные страниц | Пакетная запись (≈500 страниц на пакет), в памяти не копить |
| Сайтовые проверки (дубли и т.п.) | Считаются SQL после обхода |
| HTML | По умолчанию не хранится (только md5); `--store-html` — zstd-сжатие в отдельный SQLite-файл |
| Браузер | Лимит одновременных вкладок, автоснижение параллельности Crawlee по памяти (проверить в прототипе) |
| Объём БД | Для каждого типа ресурса раздельно `follow` (переходить) и `store` (записывать), как Crawl/Store в SF |

**Режимы хранения:** `--storage memory` (SQLite `:memory:` + очередь в памяти, в конце — SQLite backup в файл) и `--storage disk` (файл SQLite в WAL, SQL-очередь). По умолчанию выбор автоматический: `max_urls ≤ 10000` → memory, иначе disk. Если прототип покажет выигрыш memory < 20 % — режим убирается.

Удалённые БД (Postgres/MySQL) — v2; DSN хранится в keychain.

---

## 3. CLI

Принцип — **drill-down**: сначала сводка, потом детали; агент не получает 100k строк разом. Каждая команда: таблица для человека, `--json` для агента.

```
# обход
spider crawl <url> [--profile P] [--render never|always] [--max-urls N]
                   [--storage memory|disk] [--proxy ...] [--set key=value ...] [--detach]
spider crawl --list urls.txt [...]            # режим List: обход списка URL (миграции)
spider status [crawl_id]
spider analyze <crawl_id>                     # пересчитать проверки без переобхода (после смены порогов)
spider compare <id1> <id2>                    # сравнение обходов (v2)

# анализ
spider issues [crawl_id] [--severity high]
spider urls [crawl_id] --issue <code>
spider url <url>
spider links <url> --in|--out
spider export [crawl_id] --format csv|json
spider query "SELECT ..."

# управление данными
spider projects list | delete <project>
spider crawls list [--project X] | show <id> | delete <id>... | resume <id>
spider crawls prune --keep-last N | --older-than 90d [--project X]
spider db info | migrate | vacuum

# конфиг
spider config show [--profile X] --resolved   # у каждого значения — слой-источник
spider config validate <file>
spider config schema                          # JSON Schema для агентов
spider profiles list | show <name> | init <name> [--from <preset>]
```

- Удаление — с подтверждением; `--yes` для агента, `--dry-run` показывает, что удалится.
- Долгий обход: по умолчанию на переднем плане с прогрессом; `--detach` — фоновый процесс, статус всегда в БД.
- Поведение по умолчанию: уважать robots.txt, умеренная параллельность; `--ignore-robots`, `--concurrency` снимают ограничения.

---

## 4. Конфигурация и профили

Главное требование — **максимальная гибкость**: любой параметр задаётся в файле и переопределяется из командной строки.

Порядок слоёв (следующий перекрывает предыдущий):

1. Встроенные значения (pydantic-модель)
2. Глобальный конфиг `~/.config/spider/config.toml`
3. Конфиг проекта `.spider/config.toml`
4. Профиль `--profile NAME` (с наследованием `extends = "..."`)
5. Явный файл `--config path.toml`
6. Переменные окружения `SPIDER_<SECTION>__<KEY>`
7. Именованные флаги (`--max-urls`, `--render`, …) — только для частых параметров
8. `--set dotted.key=value` — для любого ключа

Встроенные пресеты: `default`, `googlebot`, `yandexbot`, `fast` (всё лишнее выключено). Пользовательские профили — в `.spider/profiles/*.toml`.

Пример профиля:

```toml
extends = "googlebot"
user_agent = "googlebot-smartphone"   # пресет или своя строка
render = "never"
max_urls = 50000
concurrency = 20
respect_robots = true
include = ["^/catalog/"]
exclude = ["\\?sort="]
headers = { "Accept-Language" = "ru" }

[collect.internal_links]
follow = true
store = false

[collect.images]
follow = false
store = true
```

**Инструкции по составлению профилей:**
- `docs/profiles.md` — справочник всех ключей (генерируется из схемы) + рецепты: быстрый аудит, миграция по списку URL, JS-сайт, обход через прокси, только битые ссылки, большой интернет-магазин.
- Скилл для ИИ-агентов (по образцу `serp`): как выбрать/составить профиль и какие команды звать для анализа.
- `spider profiles init` создаёт закомментированный шаблон с описанием каждого ключа.

---

## 5. Интеграции

- **rb-sitemap-xml** (`../sitemap-xml`) — подключается как библиотека через `[tool.uv.sources]`, локальный путь, editable. Нужные доработки соседа: отдавать метаданные URL (`lastmod`, `changefreq`, `priority`, файл-источник), async-API, команда `sitemap-xml build` для генерации sitemap (генерация живёт там, spider отдаёт список индексируемых URL).
- **Обогатители (enrichers)** — плагины через entry points, пишут в `url_metrics` по `crawl_id` + URL. В MVP — только интерфейс. Реализации (v3) — на основе соседних пакетов `google-search-console`, `yandex-webmaster`, PageSpeed Insights.

---

## 6. Тестирование

| Стенд | Назначение |
|---|---|
| **Синтетический полигон** в pytest (aiohttp-сервер) | Каждой проверке из `features.md` — своя страница-ловушка (петли редиректов, 5xx, noindex, `X-Robots-Tag`, canonical, hreflang, JS-контент…). Запускается всегда. Порог покрытия 90 % |
| **Сгенерированный статический сайт** (`bench/gen_site.py`, seed, 10k/50k/100k страниц, 50–100 КБ, дерево категорий, пагинация, перелинковка) на VPS через `hostme` | Замер скорости и памяти в режимах memory/disk. От индексации: robots.txt запрещает Googlebot/YandexBot, на страницах `meta robots noindex`. Деплой — с подтверждением пользователя |
| **Реальные сайты** (даёт пользователь) | Итоговая проверка на живых данных |

---

## 7. План работ

1. **Документы** — эта спецификация + [features.md](features.md).
2. **Прототип производительности** — Crawlee + impit + selectolax + SQL-очередь; сгенерированный сайт на 50–100k URL; метрики: страниц/с, пиковая память, корректность возобновления; memory vs disk. Решение по режиму memory.
3. **MVP** — см. волну MVP в [features.md](features.md).
4. v2 → v3 → бэклог.
