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
- Проверки контента: точные дубли (md5 HTML), «Lorem ipsum», мало текста (`thresholds.low_content_words`, 200 слов видимого текста).
- `--store-html` (`crawl.store_html`): HTML страниц сжимается zstd и хранится в `spider-html.sqlite` рядом с базой; по умолчанию — только md5.
- Настройки обхода: `max_depth`, `max_links_per_page`, `max_url_length`, `include` / `exclude` (регулярные выражения), `all_subdomains`, `stay_in_start_folder`, `max_rps`, `timeout_s`, `headers`, `content_exclude` (по умолчанию текст меню и подвала не считается), пресеты `user_agent` (googlebot, googlebot-smartphone, bingbot, yandexbot, chrome), прокси с чередованием и паролем из системного хранилища ключей; флаги `--max-depth`, `--user-agent`, `--ignore-robots`.
- robots.txt читается от имени User-Agent обхода (или `robots_user_agent`), режимы `respect` / `ignore` / `report`, соблюдается Crawl-delay.
- `spider doctor` проверяет настройки и только те секреты, которые они требуют (пароль прокси).

- Ссылки: граф ссылок (анкор, alt картинки-ссылки, rel, nofollow, тип — ссылка, canonical, редирект, refresh), `spider links <url> --in|--out`. Внешние ссылки и URL за пределами стартовой папки проверяются (код ответа), но не обходятся. Раздел `collect.*` (follow / store для внутренних и внешних ссылок, canonical, refresh), `crawl.follow_internal_nofollow`, `crawl.follow_external_nofollow`, `crawl.check_outside_start_folder`.
- 16 проверок: 12 группы Links (ссылки на localhost, «нерабочие» ссылки, тупики, входящие только с неиндексируемых / только nofollow / и те и другие, много исходящих, глубина, без анкора, неинформативный анкор), внешние нет ответа / 4xx / 5xx, Canonicals: Unlinked. Пороги `thresholds.crawl_depth`, `internal_outlinks`, `external_outlinks`, `non_descriptive_anchors`.
- Проверки, чьи данные не собирались (`collect.*` выключен), не считаются пройденными: `spider issues` перечисляет их в `not_checked`.
- Ресурсы страниц: картинки (и `srcset` по `collect.images_srcset`), CSS, JS, видео и аудио, iframe — проверяются (код ответа, вес) по `collect.images|css|js|media|iframes`, хранятся строками ссылок своего типа. robots.txt применяется ко всем скачиваемым URL, в том числе ресурсам и чужим сайтам.
- 7 проверок: картинки без alt / с пустым alt / с длинным alt / тяжелее `thresholds.image_kb` / без width и height (по URL картинки); Internal и External Blocked Resource.
- Большие обходы: очередь в памяти + таблица `frontier` в базе (отметка «обработан» пишется одной транзакцией со страницей), запись раз в 500 страниц или 2 с. `spider crawls resume` продолжает обход после Ctrl-C, падения или `kill -9` без потерь и повторных скачиваний; `spider crawl --detach` — обход в фоне (лог рядом с базой); `spider status` — прогресс (сохранено, в очереди, жив ли процесс), проект не нужен.
- Режим списка: `spider crawl --list urls.txt` (или `--list -` из stdin, ключ `crawl.mode = list`) — аудит заданных URL без перехода по ссылкам, редиректы (3xx, meta и HTTP Refresh) проходятся до конца; «свой сайт» для проверок — хосты из списка. Результат — обычный обход: все команды анализа, `--detach` и `crawls resume` работают.
- Управление данными: `spider crawls delete <id>…`, `spider crawls prune --keep-last N | --older-than 90d` (по проектам, `--project-name`), `spider projects list | delete`, `spider db info | migrate | vacuum`. Удаление спрашивает подтверждение, `--yes` (`-y`, `--confirm`) — без вопроса, `--dry-run` — показать, что удалится; идущий обход не удаляется.
- `spider url <url>` — всё о странице: ответ, on-page данные, индексируемость и причина, проблемы, число входящих и исходящих ссылок, ресурсы (картинки, CSS, JS) с кодом, весом и alt.
- `spider export [pages|links|issues] --format csv|json [-o файл]` — потоковая выгрузка (память не растёт) с фильтрами `--issue`, `--status 404|4xx` (у URL или цели ссылки), `--external`: все URL, все ссылки и анкоры, внешние ссылки, ссылки на URL с данным кодом, все находки проверок.
- `spider query "SELECT …"` — свой SQL только на чтение: база открывается read-only, SQLite отклоняет всё, кроме SELECT; `--format csv|json` — все строки потоком.
- JS-рендеринг: `spider crawl --render always` (`crawl.render`) — HTML-страницы с кодом 200 ещё и открываются в браузере (Playwright через Crawlee, extra `rb-spider[render]`), SEO-данные берутся из DOM после выполнения скриптов; коды, редиректы и ресурсы проверяются как обычно. `crawl.render_tabs` — вкладок одновременно, `crawl.render_wait_ms` — ожидание скриптов после загрузки, `pages.rendered` — данные из DOM или (сбой рендера) из сырого HTML. Без Playwright или браузера — ошибка `RENDER_UNAVAILABLE` с командой установки до начала обхода.
- Обогатители: плагины через entry points `rb_spider.enrichers` добавляют метрики к URL обхода (таблица `url_metrics`); `spider enrichers` — установленные плагины (сломанные — с причиной), `spider enrich [crawl_id] [--plugin]` — запуск, метрики видны в `spider url`. Сбой плагина — код 5 с его именем, прежние метрики остаются.
- Справка всех команд на русском с примерами и формой `--json`; тесты: у каждой команды есть docstring, у каждой опции `help=`, снимки `--help` каждой команды.

### Changed

- Большой обход вдвое быстрее и в 2 раза легче по памяти: бенч 100k страниц при 50 параллельных — ~1500 URL/с и ~325 МБ на все процессы (было 653 URL/с и 597 МБ). Разбор HTML и выбор ссылок идут в отдельных процессах (`crawl.parse_workers`, по умолчанию по числу ядер, не больше 4; маленькие обходы — в одном процессе), очередь не держит в памяти обработанные запросы, запись в базу — в отдельном потоке одним SQL-оператором на пачку, находки проверок не копятся в памяти.
- Ключ `crawl.respect_robots` заменён на `crawl.robots` (`respect` / `ignore` / `report`).

### Fixed

- Тесты больше не пишут обходы полигона в настоящую базу пользователя (общие фикстуры модулей создавались раньше подмены `SPIDER_DB_PATH`).
