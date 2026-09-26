# Changelog

Все заметные изменения фиксируются здесь. Формат —
[Keep a Changelog](https://keepachangelog.com/), версии следуют
[SemVer](https://semver.org/). Записи добавляются в `Unreleased` в том же
коммите, что и изменение.

## [Unreleased]

### Added

- Каркас CLI `spider` (пакет `rb-spider`) по архитектуре `cli-builder`: `doctor`, `init`, `status`, `config list|get|set`, `auth login|logout|status`, `skill install`, `--json`/`--ai`/`--version`, фиксированные коды выхода, секреты в системном хранилище ключей.
- `spider crawl <url>`: обход сайта в ширину (Crawlee + impit, разбор selectolax), каждый ответ — строка в базе, шаги редиректов сохраняются отдельно, `--max-urls` — точная граница, `--concurrency`.
- `spider crawls list`: обходы всех проектов, новые сверху.
- База обходов — одна на пользователя в папке данных приложения (`SPIDER_DB_PATH` переопределяет), схема через миграции Alembic; `spider doctor` показывает её путь.
- Справка всех команд на русском с примерами и формой `--json`; тесты: у каждой команды есть docstring, у каждой опции `help=`, снимки `--help` каждой команды.
