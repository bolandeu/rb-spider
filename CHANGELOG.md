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
- Движок SEO-проверок: правила после обхода (SQL или Python), типы и приоритеты как в Screaming Frog; `spider issues` — сводка, `spider urls --issue <код>` — URL проверки, `spider analyze` — пересчёт без переобхода. Первые 9 проверок группы Response Codes: нет ответа, 4xx, 5xx, петли и цепочки редиректов, 3xx, meta refresh, HTTP Refresh, запрет robots.txt.
- Обход соблюдает robots.txt (запрещённые URL попадают в отчёт), записывает URL без ответа и цели meta / HTTP Refresh.
- Настройки обхода слоями (встроенные → глобальный → проект → профиль → `--config` → `SPIDER_<РАЗДЕЛ>__<КЛЮЧ>` → флаги → `--set`), любой ключ меняется через `--set`; `spider config show` — итог и слой каждого значения, `config validate`, `config schema` (JSON Schema), `config get/set` понимают ключи настроек.
- Профили: встроенные `default`, `googlebot`, `yandexbot`, `fast`, свои в `.spider/profiles/` с наследованием `extends`; `spider profiles list|show|init`. Ключ `crawl.user_agent`.
- `spider crawls show` — обход и снимок настроек, с которыми он шёл. `docs/profiles.md` — слои, формат профиля и таблица ключей, сгенерированная из схемы.
- Справка всех команд на русском с примерами и формой `--json`; тесты: у каждой команды есть docstring, у каждой опции `help=`, снимки `--help` каждой команды.
