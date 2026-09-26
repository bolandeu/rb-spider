# Профили и настройки spider

Настройки обхода задаются слоями — каждый следующий перекрывает предыдущий:

| # | Слой | Где | Метка в `spider config show` |
| --- | --- | --- | --- |
| 1 | Встроенные значения | модель настроек в коде | `default` |
| 2 | Глобальный конфиг | `~/Library/Application Support/spider/config.toml` на macOS (`platformdirs.user_config_dir("spider")`) | `global` |
| 3 | Конфиг проекта | `.spider/config.toml` (разделы `[crawl]`…) | `project` |
| 4 | Профиль | `--profile NAME`: встроенный или `.spider/profiles/NAME.toml`, с наследованием `extends` | `profile:NAME` |
| 5 | Явный файл | `--config path.toml` | `file:path` |
| 6 | Переменные окружения | `SPIDER_<РАЗДЕЛ>__<КЛЮЧ>`, например `SPIDER_CRAWL__MAX_URLS=500` | `env` |
| 7 | Флаги команды | `--max-urls`, `--concurrency` — только частые | `flag` |
| 8 | `--set` | `--set crawl.user_agent="Bot/1.0"` — любой ключ, можно повторять | `set` |

Что получилось в итоге и откуда каждое значение — `spider config show` с теми же флагами, что у `spider crawl`.

## Формат профиля

```toml
description = "Аудит магазина глазами Googlebot"   # видно в `spider profiles list`
extends = "googlebot"                              # незаданные ключи — из этого профиля

[crawl]
max_urls = 50000
concurrency = 10
```

- Встроенные профили: `default`, `googlebot`, `yandexbot`, `fast` — `spider profiles list`.
- Свой профиль: `spider profiles init NAME --from googlebot` создаёт файл, где все ключи закомментированы и описаны.
- Проверить файл: `spider config validate FILE`; все ключи и типы машиночитаемо: `spider config schema`.
- Значения в `--set` и `SPIDER_…__…` разбираются как TOML: `500` — число, `false` — логическое, иначе строка.

## Все ключи

Таблица генерируется из модели настроек (тест сверяет её с кодом).

<!-- keys:begin (generated from the settings schema) -->
| Ключ | Тип | По умолчанию | Описание |
| --- | --- | --- | --- |
| `crawl.max_urls` | `int \| None` | — | Остановиться после стольких URL; не задано — обойти весь сайт. |
| `crawl.concurrency` | `int` | `20` | Сколько запросов к сайту выполняется одновременно. |
| `crawl.respect_robots` | `bool` | `true` | Соблюдать robots.txt: запрещённые URL не скачиваются, но попадают в отчёт. |
| `crawl.user_agent` | `str \| None` | — | Заголовок User-Agent запросов; не задано — как у обычного браузера (Firefox). |
<!-- keys:end -->

## Рецепты

Появятся вместе с настройками, на которые они опираются (#20).
