# rb-spider

SEO-краулер для технического аудита сайтов — функциональный аналог [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/) в виде Python-библиотеки и CLI `spider`.

> **Статус: в разработке.** Готов каркас CLI (`spider doctor`, `init`, `config`, `auth`); команд обхода пока нет.

## Что будет уметь

- Обходить сайт (до ~100 тыс. URL на обычном ноутбуке — память не растёт с размером сайта) или список URL.
- Находить SEO-проблемы: битые ссылки, редиректы и их цепочки, title / description / H1, директивы индексации, canonical, дубли, изображения — и дальше по [чеклисту](docs/features.md).
- Рендерить JavaScript через браузер — для сайтов, где это нужно.
- Работать через прокси, с любым User-Agent и заголовками.
- Хранить обходы в SQLite (по умолчанию) или в удалённой реляционной БД; сравнивать обходы.
- Гибкая настройка: профили в TOML с наследованием, любой параметр переопределяется из командной строки.
- Отдавать всё и человеку (таблицы), и ИИ-агенту (`--json`).

## Как это будет выглядеть

```bash
spider crawl https://example.com --profile googlebot --max-urls 50000
spider issues                       # сводка проблем по последнему обходу
spider urls --issue title_missing   # URL с конкретной проблемой
spider url https://example.com/page # всё про одну страницу
spider export --format csv
spider crawls prune --keep-last 5   # чистка старых обходов
```

## Основа

[Crawlee for Python](https://crawlee.dev/python/) (обход, прокси, браузер) + [selectolax](https://github.com/rushter/selectolax) (разбор HTML) + SQLAlchemy (хранилище). Почему именно так и что отвергнуто — в [спецификации](docs/spec.md).

## Установка

```bash
uv tool install "rb-spider @ git+https://github.com/bolandeu/rb-spider.git@vX.Y.Z"   # из git-тега вместо реестра
uv tool upgrade rb-spider                                      # обновить
spider                                                         # список команд
```

JS-рендеринг (`spider crawl --render always`) — дополнительно, с Playwright:

```bash
```

Браузер отдельно ставить не нужно, если уже есть любой Chromium в кэше Playwright (`ms-playwright`) или Google Chrome — spider найдёт его сам; другой — `--set crawl.render_browser=<путь>`. Если нет ничего: `playwright install --only-shell chromium`.

Хранилище страниц `spider fetch` (кэш, ADR 0001): индекс — таблица `cache.spider_fetches`, тела — файлы zstd в `SPIDER_CACHE_DIR` (по умолчанию кэш пользователя, на Mac `~/Library/Caches/spider/fetch`; прод — `/data/cache/spider`). Срок — `SPIDER_CACHE_TTL_DAYS` (дней, по умолчанию 90), предел файлов — `SPIDER_CACHE_MAX_GB` (по умолчанию без предела); чистит сам spider раз в сутки. Удалить каталог можно: страницы скачаются снова.
Состояние прокси между запусками — файл `proxy-state.json` в `SPIDER_CACHE_DIR` (по умолчанию кэш пользователя, на Mac `~/Library/Caches/spider/`; срок — `crawl.proxy_state_ttl_s`, 600 с); это кэш: удалить можно, цена — одна проверка прокси.

Запасной HTTP-клиент на curl (`--set crawl.http_client=curl`) — extra `curl`: `uv tool install "rb-spider[curl]" --index …`; оба extra вместе — `rb-spider[render,curl]`.

У каждой команды `--help` — это и есть документация. `--json` — вывод для агентов; `spider --ai` печатает инструкцию для ИИ-агентов, `spider skill install` ставит её в Claude Code.

## Разработка

```bash
uv sync
uvx --from "git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator.git@v1.27.1#subdirectory=gate" gate check   # гейт; тот же шаг, что в .gitea/workflows/ci.yml
```

Правила разработки — в [AGENTS.md](AGENTS.md).

## Документы

| Файл | Что внутри |
|---|---|
| [docs/spec.md](docs/spec.md) | Архитектура и принятые решения |
| [docs/features.md](docs/features.md) | Чеклист функций по волнам MVP → v2 → v3 → бэклог |
| [docs/reference/screaming-frog.md](docs/reference/screaming-frog.md) | Справочник функций и проверок Screaming Frog |
