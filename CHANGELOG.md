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
- `spider redirects [--only all|chains|errors]` — отчёт по редиректам: каждый шаг (3xx / meta / HTTP Refresh) до конечного URL и кода. Порог цепочки `thresholds.redirect_chain_hops`; `spider analyze` берёт пороги из текущих настроек (`--profile`, `--set`).
- 24 on-page проверки: Page Titles, Meta Description, H1, H2 (нет, несколько, вне `<head>`, дубли, длина, alt в H1, порядок заголовков, title = H1). Пороги длины — раздел `thresholds`. Дубли ищутся одним проходом (оконная функция SQL), без сравнения каждой страницы с каждой.
- Сбой соединения больше не печатает трассировку Crawlee: такие URL и так попадают в отчёт (`internal_no_response`).
- 19 проверок директив и canonical: noindex / nofollow / none / nosnippet / noimageindex / unavailable_after / notranslate / устаревшие noodp и noydir (meta robots и X-Robots-Tag), meta robots вне `<head>`; canonical — нет, несколько, конфликт, вне `<head>`, лишние атрибуты, фрагмент, относительный, склейка с другим URL, ведёт на неиндексируемый URL (canonical из HTML и заголовка Link).
- Индексируемость каждого URL и причина (как Indexability Status в Screaming Frog); проверки дублей учитывают только индексируемые страницы. Цели canonical тоже обходятся.
- Справка всех команд на русском с примерами и формой `--json`; тесты: у каждой команды есть docstring, у каждой опции `help=`, снимки `--help` каждой команды.
