# rb-spider

SEO-краулер для технического аудита сайтов — функциональный аналог [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/) в виде Python-библиотеки и CLI `spider`.

> **Статус: в разработке.** Готовы спецификация и чеклист функций, кода пока нет.

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

## Документы

| Файл | Что внутри |
|---|---|
| [docs/spec.md](docs/spec.md) | Архитектура и принятые решения |
| [docs/features.md](docs/features.md) | Чеклист функций по волнам MVP → v2 → v3 → бэклог |
| [docs/reference/screaming-frog.md](docs/reference/screaming-frog.md) | Справочник функций и проверок Screaming Frog |
