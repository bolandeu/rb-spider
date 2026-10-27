# rb-spider — спецификация

SEO-краулер для технического аудита сайтов, функциональный аналог [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/).
Python-библиотека `rb_spider` + CLI `spider`. Пользователь — один человек из терминала и ИИ-агенты (интерфейс команд рассчитан на обоих).

Полный перечень функций и проверок по волнам — в [features.md](features.md).

---

## 1. Стек и выбор библиотек

| Слой | Выбор | Почему | Отвергнуто |
|---|---|---|---|
| Движок обхода | **Crawlee for Python** (`HttpCrawler`, версия пинится) | Очередь, автомасштабирование, прокси (ротация, tiered), robots.txt, возобновление, Playwright — из коробки. Apache-2.0, активно развивается (1.10.x, 09.2026) | **Scrapy** — решение пользователя; свой движок на httpx — пришлось бы писать очередь/прокси/рендеринг самим |
| HTTP-клиент | **ImpitHttpClient** (дефолт Crawlee, Rust, HTTP/2–3, браузерный отпечаток) | Самый быстрый из доступных в Crawlee | httpx — медленнее; `CurlImpersonateHttpClient` — переключаемый запасной (`crawl.http_client = "curl"`, extra `rb-spider[curl]`) |
| Парсинг HTML | **selectolax** (Lexbor) | В 3–4× быстрее lxml. Извлечение SEO-данных — наш код, не привязан к движку: одинаково работает по сырому и отрендеренному HTML | `ParselCrawler` / BeautifulSoup — медленнее; lxml/parsel — только для пользовательских XPath (v2) |
| JS-рендеринг | **Гибрид**: обход по HTTP как обычно (коды, заголовки, каждый шаг редиректа, проверка ресурсов), HTML-страницы с кодом 200 дополнительно открываются в браузере — Playwright через `BrowserPool` Crawlee (extra `rb-spider[render]`), данные — из готового DOM тем же `parse_page`, исходный HTML разбирается рядом (колонки `raw_*`, `links.origin`). `crawl.render` (`never` / `always` / `auto`), `render_tabs`, `render_wait_ms`, `render_viewport`, `render_console`, `render_flatten_*`; `pages.rendered` — откуда данные; консоль и незагруженные ресурсы — `render_events`. `auto` — свой детерминированный выбор: рендерятся первые `render_auto_sample` HTML-страниц, если JS ни на одной ничего не поменял (ссылки, текст, title, description, h1, canonical, директивы) — остальные без браузера. Уход скриптом на другой URL — редирект `refresh_kind = javascript`. Ресурсы, закрытые robots.txt, браузер не грузит (как Googlebot) | Как у Screaming Frog; ресурсы не гоняются через браузер | `PlaywrightCrawler` (решение пересмотрено в #15): браузер сам проходит редиректы — пропадают шаги 3xx, ресурсы пришлось бы проверять отдельным клиентом; `AdaptivePlaywrightCrawler` для `auto` (#39) — непредсказуем для аудита (ML-предиктор решает по странице, один и тот же сайт даёт разные данные) и требует `PlaywrightCrawler` вместо гибрида |
| Хранилище результатов | **Своя схема на SQLAlchemy 2 + Alembic** | Нужны нормальные таблицы и связи (граф ссылок, отчёты SQL-ом); один код для SQLite / Postgres / MySQL | Датасет Crawlee — JSON-блобы без колонок, SQL-запросов нет |
| Очередь обхода | **Своя очередь** (`RequestManager` Crawlee): в памяти + свой фильтр виденных URL, сохраняется пачками в ту же SQLite **в одной транзакции с результатами** | Прототип (#3): в 5–7× быстрее дисковых очередей Crawlee; возобновление без потерь | `SqlStorageClient` (180 стр/с, при `kill -9` потерял 266 из 10k страниц); `FileSystemStorageClient` (319 стр/с, тот же риск потерь) |
| Структурированные данные (v2) | extruct для Microdata и RDFa (extra `rb-spider[structured]`), JSON-LD — свой разбор по дереву selectolax; словарь Schema.org — таблица из официального релиза (`scripts/build_schemaorg.py`), функции Google — своя таблица обязательных и рекомендуемых свойств | extruct приводит Microdata и RDFa к форме JSON-LD (`uniform`); JSON-LD через extruct стоил бы повторного разбора страницы lxml, а разбор HTML — узкое место обхода | валидатор Google (нет офлайн-версии), pyld (разворачивание JSON-LD по сети) |
| Размер картинок (v2) | imagesize — размер из заголовка файла (PNG, JPEG, GIF, WebP, AVIF, SVG…), чистый Python без зависимостей, MIT; отображаемый размер — из браузера при рендеринге (`crawl.render_images`) | Картинка уже скачана для проверки кода и веса, заголовок читается без декодирования; используется Sphinx, поддерживается | Pillow — десятки МБ ради чтения заголовка, декодирует картинку; свой разбор форматов — повторение готового |
| Почти-дубли (v2) | datasketch (MinHash), extra `rb-spider[near]` — тянет numpy и scipy | Поддерживается; подпись считается при обходе (`collect.near_duplicates`), пары — полосами LSH во временных таблицах SQLite (`core/duplicates.py`), без индекса LSH в памяти | пакет `simhash` — заброшен; `MinHashLSH` datasketch — держит весь индекс в памяти |
| robots.txt | protego (через Crawlee) | Уже внутри Crawlee | reppy — заброшен |
| Sitemap | соседний пакет **rb-sitemap-xml** | Свой, развиваем | ultimate-sitemap-parser — GPL-3.0 |
| Конфиг | **pydantic** + своё слияние слоёв (~40 строк, `core/settings.py`) | Слияние плоских `раздел.ключ` запоминает слой каждого значения — это нужно `config show`; схема и описания — из pydantic | pydantic-settings — не хранит, из какого слоя пришло значение |
| CLI | Архитектура скилла `cli-builder`: Python 3.12+, uv, Typer, конфиг проекта, секреты в keychain, вывод человек/`--json`, ИИ-понятные ошибки, коды выхода | Единая архитектура всех CLI пользователя | — |

Готовые SEO-краулеры (advertools — на Scrapy, SEOnaut — Go, LibreCrawl, pyseoanalyzer) как зависимость не берём; advertools и SEOnaut — источник списков колонок и проверок.

---

## 2. Модель данных

- Иерархия: **project** (сайт) → **crawl** (один запуск) → строки данных с `crawl_id`.

**Где лежат данные** (как у соседнего `serp`):

| Что | Где | В git? |
|---|---|---|
| База обходов (все проекты) | `platformdirs.user_data_dir("spider")/spider.sqlite` — на macOS `~/Library/Application Support/spider/`; переопределяется `SPIDER_DB_PATH`; `SPIDER_DATABASE_URL` — общий PostgreSQL на сервере | нет |
| Хранилище страниц `spider fetch` | индекс — таблица `spider_fetches` (кэш, схема `cache` на PostgreSQL); исходник страницы и Markdown — файлы zstd в `SPIDER_CACHE_DIR`, по умолчанию `platformdirs.user_cache_path("spider")/fetch` (на macOS `~/Library/Caches/spider/fetch`) | нет |
| Сжатый HTML (`--store-html`) | рядом с базой: `spider-html.sqlite`, zstd (библиотека `zstandard`; встроенный `compression.zstd` есть только с Python 3.14) — на стенде сжатие ~5× | нет |
| Конфиг проекта и профили | `.spider/` в каталоге проекта (`config.toml`, `profiles/*.toml`) | да |
| Секреты (прокси, DSN) | системное хранилище ключей или `SPIDER_<PROVIDER>_<FIELD>` | никогда |

Не папка кэша (Caches): это история обходов, а кэш чистят ОС и программы-уборщики. Одна база на пользователя, а не файл на проект: сравнение обходов, `crawls list` и `prune` работают по всем проектам, репозиторий не засоряется. Проект в базе — по имени из `.spider/config.toml`.
- Таблицы (всё с префиксом `spider_`, объявлены в `core/tables.py`): `spider_projects`, `spider_crawls` (статус, итоговый конфиг-снимок), `spider_pages`, `spider_issues`, `spider_frontier`, `spider_url_metrics` (для обогатителей), `spider_urls` + `spider_link_rows` (ссылки по числовым id URL, #23) и представление `spider_links` с URL текстом для проверок, отчётов и `spider query`; сжатый HTML — в отдельном файле. У каждой таблицы PRIMARY KEY (Directus): где естественного ключа нет — суррогатный `id` (в SQLite — псевдоним rowid). Другие инструменты читают только представления `spider_v1_*` (`crawls`, `pages`, `issues`, `links`); в v1 колонки только добавляются в конце, иная форма — `spider_v2_*`. Общие ключи (T50): `url_key` и `domain_key` в `spider_pages` и `spider_urls` (индекс по `url_key`) — `rb_keys.norm_url` / `norm_domain` из соседнего пакета rb-keys (контракт — `vectors/keys-v1.yaml` в его репозитории), считаются при записи; не веб-URL (mailto:, кривой адрес) — NULL, не пустая строка. `spider_v1_pages` публикует ключи страницы, `spider_v1_links` — ключи цели ссылки; по ним Directus связывает страницы конкурентов и клиентов.
- **Ссылки по id URL (#23):** URL-строка хранится в `urls` один раз на обход, строка ссылки — два целых. Id присваивает сам SQLite при записи пачки (`INSERT OR IGNORE` + `JOIN`), словаря URL→id в памяти нет. Проверки и отчёты читают представление `links`; планировщику SQLite нужна статистика (`ANALYZE` с `analysis_limit` в начале `analyze`), иначе фильтр по URL превращается в перебор всех ссылок обхода. Тяжёлые группировки (счётчики ссылок, правила по цели ссылки) группируют `link_rows` по id и подставляют URL в конце. Отвергнуто: DuckDB для анализа — после #23 проверки идут ~34 с на 100k, это полные проходы по 3,3 млн ссылок по одному на правило; ускорение дало бы объединение правил в общий проход, а не смена СУБД.
- **Хранилище страниц `spider fetch`** ([ADR 0001](adr/0001-fetch-storage.md)): повторный `spider fetch` того же URL в том же режиме (`--render` или без) в пределах срока берётся из хранилища и не запрашивает сайт — ни страницу, ни проверку прокси. Своя таблица `spider_fetches` (`info={"kind": "cache"}`, не `spider_pages`: у fetch нет обхода, есть срок), строка на (`url_key`, `rendered`); тела — файлы zstd, имя — случайный `cache_key`. Хранится HTML-ответ с кодом ниже 500, кроме 429. Срок — `SPIDER_CACHE_TTL_DAYS` (90), предел — `SPIDER_CACHE_MAX_GB`; чистку раз в день делает сам spider (просроченное, сверх предела, файлы без строки старше суток). `--fresh` — мимо хранилища, `--max-age <дней>` — свой срок; в библиотеке хранилище выключено (`store=False`).
- Итоговый (resolved) конфиг каждого обхода сохраняется в `crawls` — чтобы объяснять разницу между обходами.
- Проверки (issues): в основном **SQL-представления** поверх таблиц обхода; сложные — Python. Пороги (длина title и т.п.) — из конфига. Проверка, которой нужны невыключенные данные, получает статус «не проверялось», а не «ок».

### Большие обходы (цель — 100k URL на Mac без роста ОЗУ)

| Что растёт | Мера |
|---|---|
| Очередь и виденные URL | Своя очередь (`core/queue.py`, `RequestManager` Crawlee): ожидающие URL — кортежи, `Request` живёт только пока запрос в работе (очередь Crawlee в памяти держала все 100k `Request` по ~2,3 КБ); множество виденных URL; зеркало в таблице `frontier` пачками |
| Процессор | Разбор HTML и выбор ссылок (`core/scope.py`) — в пуле процессов (`crawl.parse_workers`); основной процесс — цикл событий Crawlee, очередь, запись. Пачка пишется потоком-писателем одним `INSERT … SELECT FROM json_each(?)`: SQLite работает без GIL (`executemany` возвращает GIL после каждой строки — запись шла втрое медленнее) |
| Граф ссылок, данные страниц | Пакетная запись (≈500 страниц на пакет), в памяти не копить |
| Сайтовые проверки (дубли и т.п.) | Считаются SQL после обхода |
| HTML | По умолчанию не хранится (только md5); `--store-html` — zstd-сжатие в отдельный SQLite-файл |
| Браузер | Лимит одновременных вкладок `crawl.render_tabs`; картинки, медиа и шрифты в браузере не загружаются |
| Объём БД | Для каждого типа ресурса раздельно `follow` (переходить) и `store` (записывать), как Crawl/Store в SF |

**Режимов хранения memory/disk нет** (решение по прототипу #3): результаты всегда пишутся пакетами в SQLite-файл (WAL). В прототипе (без графа ссылок) это 4 с из 77; с графом ссылок (~33 строки на страницу, два индекса по строковым URL) запись — ~0,3 мс процессора на страницу, поэтому она вынесена в отдельный поток.

**Замер MVP (#14)**, те же условия, 100k страниц, 50 параллельных, `--ignore-robots`: обход ~1500 URL/с (58–69 с), пик памяти всех процессов ~325 МБ (основной ~180 МБ + 4 разборщика по ~35 МБ); с установленным extra `render` ~400 МБ — Crawlee при импорте сразу грузит Playwright и browserforge, даже если обход без рендеринга, проверки после обхода ещё ~35 с, база 784 МБ. После #25 (время ответа, заголовки, счётчики ссылок): ~1500 URL/с, проверки ~38 с, база 799 МБ; после #23 (ссылки по id URL): **~1935 URL/с, база 400 МБ, проверки ~34 с**, память ~410 МБ; время ответа меряется обёрткой вокруг `HttpClient.crawl` — навигационные хуки Crawlee стоили ~15 % скорости. Дальше объём базы и время проверок упираются в схему: URL хранятся строками в каждой строке `links` (3,3 млн строк на 100k).

**Возобновление без потерь:** отметка «URL обработан» и результаты страницы записываются в одной транзакции. Иначе при падении теряются страницы, чьи результаты ещё в буфере (прототип: −266 из 10k).

**Замеры прототипа** (Mac M-серии, 16 ГБ; страницы ~60 КБ; своя очередь в памяти + фильтр виденных URL; ветка `prototype/perf`):

| Стенд | Параллельность | Скорость | Пик памяти |
|---|---|---|---|
| Локально, 100k страниц | 50 | 1297 стр/с (77 с) | 407 МБ |
| VPS `spider.bolandau.ru`, 20k страниц, задержка ~55 мс | 5 / 10 / 20 | 92 / 189 / 357 стр/с | 177 МБ |

По сети скорость растёт линейно с параллельностью (задержка ответа не меняется) — предел задаёт сервер сайта, а не краулер. Разбор HTML selectolax — ~0,55 мс на страницу.

**PostgreSQL (#41; общая база — с 0.3).** `SPIDER_DATABASE_URL=postgresql://пользователь@хост/база` — обходы в общем PostgreSQL на сервере (homeserver, рядом с Directus и другими инструментами; `SPIDER_DB_URL` — старое имя, читается с предупреждением; драйвер psycopg 3 — обычная зависимость); Mac работает только на локальной SQLite; пароль — в keychain (`spider auth login --provider database`) или в самом URL. Не вся строка DSN в keychain, а только пароль: адрес базы не секрет, его удобно видеть в `doctor` и `db info`, а выбор базы переменной окружения не заставляет каждую команду ходить в keychain. Решения:

- База общая (схема `public`, cli-generator architecture.md §12): у spider только объекты `spider_*` и таблица версий `alembic_version_spider`; ни перегрузок встроенных функций, ни агрегатов — они изменили бы запросы других инструментов. SQL проверок и отчётов один на обе СУБД: счётчики по условию — `count(CASE WHEN … THEN 1 END)` (`sqltext.count_if`), склейка — `string_agg` (нужен SQLite ≥ 3.44), постраничное чтение — по `id`; `x GLOB 'префикс*'` (в SQLite ради индекса) и `instr()` переписываются в `LIKE` / `strpos()` обработчиком запросов движка PostgreSQL; единственная своя функция — `spider_casefold` (в SQLite — Python, в PostgreSQL — `lower`). Что так не закрыть — написано в общем подмножестве: `coalesce(флаг, FALSE)`, `TRUE` вместо `1`, `IS DISTINCT FROM`, HAVING без псевдонимов, `NO_LIMIT` вместо `LIMIT -1`, upsert через `storage.insert_or_replace`.
- Запись пачками та же — одна команда на пачку: в SQLite `json_each`, в PostgreSQL `json_array_elements` с приведением типов и `ON CONFLICT`.
- Общая база не мигрирует при открытии: команды только сверяют ревизию (`DATABASE_NOT_MIGRATED` / `CLI_TOO_OLD`), миграции — `spider db upgrade` из релиза, под advisory lock. Новая база получает литеральную схему ревизии 0033 (`migrations/pg_baseline.py`) и дальше идёт по цепочке; миграции 0001–0032 — история SQLite. Каждая следующая миграция работает на обеих СУБД и совместима с кодом предыдущего релиза (expand/contract). Перенос локальной базы — `spider db import-sqlite` (разово, в пустую базу).
- `spider query` в PostgreSQL — транзакция только для чтения и подготовленный запрос (несколько команд через `;` не проходят); для полной гарантии — пользователь с правом только на SELECT.
- Сохранённый HTML остаётся локальным файлом SQLite (по файлу на имя удалённой базы) — это кэш для выгрузок, не данные обхода.
- Тесты: весь набор гоняется и на PostgreSQL (`scripts/pg_test.sh` или `scripts/check.sh --pg` — одноразовый контейнер postgres:16 на порту от Docker, `TEST_DATABASE_URL`), каждая проверка — на той же базе-ловушке.
- **MySQL — в backlog**: уникальный индекс по URL упирается в предел ключа (3072 байта, URL бывают длиннее), `||` там логическое ИЛИ, нет `CAST(… AS TEXT)` и `FILTER`, у TEXT-колонок нет индексов без длины префикса — это отдельная схема, а не прослойка.

---

## 3. CLI

Принцип — **drill-down**: сначала сводка, потом детали; агент не получает 100k строк разом. Каждая команда: таблица для человека, `--json` для агента.

```
# обход
spider crawl <url> [--profile P] [--render never|always] [--max-urls N]
                   [--proxy ...] [--set key=value ...] [--detach]
spider crawl --list urls.txt [...]            # режим List: обход списка URL (миграции)
spider status [crawl_id]
spider analyze <crawl_id>                     # пересчитать проверки без переобхода (после смены порогов)
spider compare <id1> <id2>                    # сравнение обходов (v2)

# анализ
spider issues [crawl_id] [--severity high]
spider urls [crawl_id] --issue <code>
spider url <url>
spider fetch <url>... | --list f [--render] [--include …] [--markdown] [--fresh] [--max-age D]   # страницы без обхода, повтор — из хранилища страниц (Python: rb_spider.fetch)
spider links <url> --in|--out
spider export [crawl_id] --format csv|json
spider query "SELECT ..."

# управление данными
spider projects list | delete <project>
spider crawls list [--project X] | show <id> | delete <id>... | resume <id>
spider crawls prune --keep-last N | --older-than 90d [--project X]
spider db info | migrate | vacuum

# конфиг
spider config show [--profile X] [--set k=v]   # итог, у каждого значения — слой-источник
spider config validate <file>
spider config schema                          # JSON Schema для агентов
spider profiles list | show <name> | init <name> [--from <preset>]
```

- Удаление — с подтверждением; `--yes` для агента, `--dry-run` показывает, что удалится.
- Долгий обход: по умолчанию на переднем плане с прогрессом; `--detach` — фоновый процесс, статус всегда в БД.
- Поведение по умолчанию: уважать robots.txt, умеренная параллельность; `--ignore-robots`, `--concurrency` снимают ограничения.
- robots.txt проверяет сам spider (парсер Crawlee `RobotsTxtFile`), а не Crawlee: Crawlee читает его только от имени `*`, а обход «глазами Googlebot» должен следовать группе Googlebot; режим `report` требует вердикта без пропуска URL. Crawl-delay превращается в ограничение запросов в минуту (сайт в обходе один).

---

## 4. Конфигурация и профили

Главное требование — **максимальная гибкость**: любой параметр задаётся в файле и переопределяется из командной строки.

Порядок слоёв (следующий перекрывает предыдущий):

1. Встроенные значения (pydantic-модель)
2. Глобальный конфиг `platformdirs.user_config_dir("spider")/config.toml` (macOS: `~/Library/Application Support/spider/`)
3. Конфиг проекта `.spider/config.toml`
4. Профиль `--profile NAME` (с наследованием `extends = "..."`)
5. Явный файл `--config path.toml`
6. Переменные окружения `SPIDER_<SECTION>__<KEY>`
7. Именованные флаги (`--max-urls`, `--render`, …) — только для частых параметров
8. `--set dotted.key=value` — для любого ключа

Встроенные пресеты: `default`, `googlebot`, `yandexbot`, `fast` (всё лишнее выключено). Пользовательские профили — в `.spider/profiles/*.toml`.

Ключи сгруппированы по разделам — TOML-таблицам (`[crawl]`, дальше `[collect]`, `[http]`…); путь ключа для `--set` и env — `раздел.ключ`. Слой вносит только явно заданные ключи, поэтому проектный файл не перекрывает глобальный значениями по умолчанию. Действующий справочник ключей — `docs/profiles.md` (генерируется). Пример профиля (часть ключей появится в своих задачах — #7, #9, #15):

```toml
description = "Магазин глазами Googlebot"
extends = "googlebot"

[crawl]
max_urls = 50000
concurrency = 20
robots = "respect"            # respect | ignore | report
user_agent = "googlebot-smartphone"   # пресет или строка целиком
render = "never"              # never | always | auto (JS-рендеринг браузером)
include = ["/catalog/"]       # регулярные выражения
exclude = ["\\?sort="]
headers = { "Accept-Language" = "ru" }
proxy_urls = ["http://user:{password}@proxy:8000"]   # пароль — spider auth login --provider proxy
proxy_fallback = "stop"       # stop | direct — если прокси не работает

[collect.internal_links]
follow = true
store = false

[collect.images]
follow = false
store = true
```

**Инструкции по составлению профилей:**
- **Прокси несёт весь трафик к сайту** (страницы, robots.txt, sitemap, браузер) и никогда не обходится молча: мёртвый прокси (проверка перед стартом, `proxy_max_failures` ошибок подряд) — остановка с `PROXY_UNAVAILABLE` и `crawls resume`, либо `proxy_fallback = direct` / ответ «да» в терминале. URL, упавшие из-за прокси, не записываются ошибками — запрашиваются снова. Мобильный прокси: `proxy_mode = failover` (входы модема по очереди), смена IP по ссылкам провайдера (`proxy_change_ip_urls`, ключ `{key}` — секрет `proxy_key`), когда сайт отвечает `proxy_change_ip_on`; запрос с блоком повторяется с новым IP и в базу не попадает; три смены подряд, на которые сайт отвечал только блоком, — смена прекращается. Логика — `core/proxy.py`. Отпечаток браузера (`crawl.fingerprint`, `core/fingerprint.py`): файл в папке пользователя, в браузер — через browserforge (генератор отпечатков Crawlee), свой код — только перевод файла в его формат, client hints и проверки согласованности (ОС, машина при рендеринге, страна/часовой пояс выходного IP по ipinfo.io через прокси).
- `docs/profiles.md` — справочник всех ключей (генерируется из схемы) + рецепты: быстрый аудит, миграция по списку URL, JS-сайт, обход через прокси, только битые ссылки, большой интернет-магазин.
- Скилл для ИИ-агентов (по образцу `serp`): как выбрать/составить профиль и какие команды звать для анализа.
- `spider profiles init` создаёт закомментированный шаблон с описанием каждого ключа.

---

## 5. Интеграции

- **rb-sitemap-xml** (репозиторий `bolandeu/sitemap-xml`) — подключается как библиотека, extra `rb-spider[sitemaps]`: `rb-sitemap-xml>=0.1,<0.2`, в `[tool.uv.sources]` — git по тегу (`v0.1.3`), как у всех наших пакетов (tools/docs/standard-release.md §5; локальный `path =` не коммитится — с невыпущенной версией работают через `uv pip install -e ../sitemap-xml`). Без extra `sitemaps.crawl` отказывает с `SITEMAPS_UNAVAILABLE`. Установка с пакетом — `uv tool install "rb-spider[sitemaps] @ git+…"`. spider берёт `SitemapClient.iter_files()` (файлы по одному со статистикой `SitemapFile`, записи с файлом-источником, картинками, hreflang) и `write_sitemaps()` (генерация — `spider sitemaps build`; команда `sitemap-xml build` — то же для списка URL). Файлы sitemap качаются httpx пакета: с User-Agent, timeout, `verify_tls` и прокси обхода (первый адрес `crawl.proxy_urls`, `SitemapClient(proxy=…)` с v0.1.3).
- **Обогатители (enrichers)** — плагины через entry points группы `rb_spider.enrichers` (класс или объект с `description` и `enrich(crawl: CrawlInfo) -> Iterable[Metric]`, `core/enrich.py`), пишут в `url_metrics` (`crawl_id`, `url`, `source` = имя entry point, `name`, `value`, `text`) пачками, повторный запуск заменяет метрики плагина, сбой плагина оставляет прежние. URL метрики может быть не из обхода (основа для Orphan Pages). В MVP — только интерфейс.
- **Интеграции с внешними API (v3) — необязательны и делаются по запросу**, когда нужен съём данных конкретным инструментом; spider полностью работает без них (как SF без API Access), проверки без данных — «не проверялось».
- **Адаптер — в spider, данные и ключи — у инструментов набора** (решение пользователя, вариант Б): обогатители для Search Console и PageSpeed Insights (пакет `gsc`, бывший `rb-gsc`), GA4 (отдельный инструмент набора — пакета пока нет) и Яндекс.Вебмастера (`ywm` + `yandex-oauth`) живут в spider как extras (`rb-spider[gsc]`, `rb-spider[ga4]`, `rb-spider[ywm]`) и вызывают соседний пакет как библиотеку. Соседний пакет ничего не знает о spider; ключи и авторизация (OAuth, ключ PSI) хранятся и обновляются у него (`gsc auth`, `ywm auth`), spider их не хранит и не спрашивает — при отсутствии авторизации сообщает, какой командой войти. Что spider нужно от `gsc` — задачи #42, #45, #46 (от инструмента GA4 — #52, то же по смыслу): стабильный импортируемый API, постраничные итераторы (Search Analytics; у GA4 — отчёт по pagePath + hostName), полный разбор URL Inspection и ответа PSI (все аудиты Lighthouse, CrUX), `auth_status()`, `property_for(url)`, типизированные ошибки и квоты, фейковый клиент для тестов.
- **Версия `gsc` для spider — закрепиться на v0.3.0.** Её API, которое ТЗ spider должно учитывать: `gsc.CrUX` (полевые данные), новые параметры `iter_search_analytics` (`by_day`, `aggregation_type`) и новые поля результата PageSpeed. Перед #42 / #45 / #46 — сверить с кодом `gsc` v0.3.0.
- SERP, Wordstat, Majestic / Ahrefs / Moz к spider не подключаются (Majestic и др. — `backlog`).
- **Скорость и мобильные проверки — `spider lighthouse` (#44), без ключей API.** Lighthouse (npm, движок PageSpeed Insights) запускается на этой машине командой `lighthouse.command` для каждой страницы, JSON-отчёт разбирается, все аудиты — в `lighthouse_audits`, проверки групп PageSpeed (19) и Mobile считаются из таблицы (`issues.refresh` — только они, без полного analyze). **Зависимость: Node.js и npm-пакет `lighthouse`** (`npm install -g lighthouse` или `lighthouse.command = "npx --yes lighthouse"`), Chrome — Chromium из кэша Playwright; `spider doctor` показывает, найден ли Lighthouse (на healthy не влияет), без него — `LIGHTHOUSE_UNAVAILABLE` с командой установки. **Все страницы не замеряются**: проблемы скорости — у шаблона, по умолчанию выборка типовых посадочных (главная + `per_template` страниц на шаблон «папка × глубина пути» с наибольшим числом входящих ссылок, не больше `max_pages`); конкретные URL или `--all` — явно. Lighthouse 12+ убрал проверки ширины контента и размера шрифта на телефоне — spider меряет их сам в браузере с экраном телефона (`spider-content-width`, `spider-font-size`) по прежним определениям Lighthouse. PageSpeed Insights (#42) — второй, необязательный источник тех же аудитов: `lighthouse.source = psi` (`--source psi`), данные — `gsc.PageSpeed().analyze_many` (extra `gsc`, git по тегу `v0.3.0`; ключ, лимиты и повторы — у gsc), аудиты — в ту же `lighthouse_audits` (колонка `source`), поэтому проверки и отчёты общие; CrUX (полевые данные реальных пользователей) — строки `crux:<метрика>` / `crux-origin:<метрика>` той же таблицы (score 1 / 0,5 / 0 = FAST / AVERAGE / SLOW, value — 75-й перцентиль). Мобильные замеры ширины контента и шрифта при любом источнике идут в браузере на этой машине. Тесты — на `gsc.testing.FakePageSpeed`.
- **LLM-провайдеры** (OpenAI, Anthropic, Gemini, Ollama…: промпты к страницам, эмбеддинги, семантическая близость) — только через `llmkit`, мост пользователя к провайдерам (цепочки моделей, кэш, учёт расходов, ключи у него). Своих клиентов провайдеров и своих LLM-ключей в spider нет.

---

## 6. Тестирование

| Стенд | Назначение |
|---|---|
| **Синтетический полигон** в pytest (aiohttp-сервер) | Каждой проверке из `features.md` — своя страница-ловушка (петли редиректов, 5xx, noindex, `X-Robots-Tag`, canonical, hreflang, JS-контент…). Запускается всегда. Порог покрытия 90 % |
| **Стенд-сайт** (`bench/bench_site.py`: `serve` — локально без файлов на диске, `build` — статика для VPS; seed, дерево категорий, пагинация, перелинковка, ~60 КБ) и `spider.bolandau.ru` через `hostme` (VPS: 1 ядро, 4 ГБ свободно — не больше ~20k страниц) | Замер скорости и памяти. От индексации: robots.txt запрещает Googlebot/YandexBot, на страницах `meta robots noindex`. Деплой — с подтверждением пользователя |
| **Реальные сайты** (даёт пользователь) | Итоговая проверка на живых данных |

---

## 7. План работ

1. **Документы** — эта спецификация + [features.md](features.md).
2. ~~**Прототип производительности**~~ — сделан (#3), итоги в разделе 2.
3. **MVP** — см. волну MVP в [features.md](features.md).
4. v2 → v3 → бэклог.
