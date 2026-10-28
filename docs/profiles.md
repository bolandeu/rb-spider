# Профили и настройки spider

Настройки обхода задаются слоями — каждый следующий перекрывает предыдущий:

| # | Слой | Где | Метка в `spider config show` |
| --- | --- | --- | --- |
| 1 | Встроенные значения | модель настроек в коде | `default` |
| 2 | Глобальный конфиг | `~/Library/Application Support/spider/config.toml` на macOS (`platformdirs.user_config_dir("spider")`) | `global` |
| 3 | Конфиг проекта | `.spider/config.toml` (разделы `[crawl]`…) | `project` |
| 4 | Профиль | `--profile NAME`: встроенный, свой для всех проектов (`profiles/NAME.toml` рядом с глобальным конфигом) или `.spider/profiles/NAME.toml`, с наследованием `extends` | `profile:NAME` |
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
- Свой профиль: `spider profiles init NAME --from googlebot` создаёт файл, где все ключи закомментированы и описаны; с `--user` — для всех проектов (`~/.config/spider/profiles/` на Linux, `~/Library/Application Support/spider/profiles/` на macOS). Проектный профиль заменяет пользовательский с тем же именем, пользовательский — встроенный.
- Проверить файл: `spider config validate FILE`; все ключи и типы машиночитаемо: `spider config schema`.
- Значения в `--set` и `SPIDER_…__…` разбираются как TOML: `500` — число, `false` — логическое, иначе строка.

## Все ключи

Таблица генерируется из модели настроек (тест сверяет её с кодом).

<!-- keys:begin (generated from the settings schema) -->
| Ключ | Тип | По умолчанию | Описание |
| --- | --- | --- | --- |
| `crawl.mode` | `Literal['spider', 'list']` | `"spider"` | spider — обход по ссылкам от стартового URL; list — только URL из списка (`spider crawl --list`) и шаги их редиректов, без перехода по ссылкам. |
| `crawl.max_urls` | `int \| None` | — | Остановиться после стольких URL; не задано — обойти весь сайт. |
| `crawl.max_depth` | `int \| None` | — | Не идти глубже стольких кликов от стартового URL; не задано — без ограничения. |
| `crawl.max_links_per_page` | `int \| None` | `10000` | Брать с одной страницы не больше стольких ссылок; не задано — все. |
| `crawl.max_url_length` | `int` | `2000` | Не обходить URL длиннее стольких символов. |
| `crawl.max_redirects` | `int` | `20` | Проходить не больше стольких шагов одной цепочки редиректов (3xx). |
| `crawl.include` | `list[str]` | `[]` | Обходить только URL, где находится хотя бы одно из этих регулярных выражений. |
| `crawl.exclude` | `list[str]` | `[]` | Не обходить URL, где находится любое из этих регулярных выражений (важнее include). |
| `crawl.all_subdomains` | `bool` | `false` | Считать поддомены (blog.site.ru и т.п.) частью сайта и обходить их. |
| `crawl.stay_in_start_folder` | `bool` | `false` | Обходить только внутри папки стартового URL (старт /blog/ — только /blog/…). |
| `crawl.check_outside_start_folder` | `bool` | `true` | С stay_in_start_folder: ссылки за пределами папки проверять (код ответа), но не обходить. |
| `crawl.cdns` | `list[str]` | `[]` | Домены CDN, которые считать частью сайта (и их поддомены): их URL обходятся как свои. |
| `crawl.keep_fragments` | `bool` | `false` | Считать URL с разными #фрагментами разными страницами (SPA на #). |
| `crawl.crawl_invalid_links` | `bool` | `false` | Обходить и синтаксически битые ссылки (без хоста, вида http:/site); иначе они отбрасываются. |
| `crawl.list_follow_canonicals` | `bool` | `false` | В режиме списка обходить и цели canonical. |
| `crawl.follow_internal_nofollow` | `bool` | `false` | Обходить внутренние ссылки с rel=nofollow. |
| `crawl.follow_external_nofollow` | `bool` | `false` | Проверять внешние ссылки с rel=nofollow. |
| `crawl.content_exclude` | `list[str]` | `["nav", "footer"]` | CSS-селекторы блоков, которые не считаются текстом страницы (число слов, «Lorem ipsum»). |
| `crawl.max_page_size_kb` | `int \| None` | — | Страницы тяжелее стольких КБ не разбирать (код и размер записываются); не задано — все. |
| `crawl.max_urls_per_depth` | `int \| None` | — | Не больше стольких URL на каждом уровне глубины; не задано — без ограничения. |
| `crawl.max_folder_depth` | `int \| None` | — | Не обходить URL глубже стольких папок в пути (/a/b/c — 3); не задано — любые. |
| `crawl.max_query_params` | `int \| None` | — | Не обходить URL с большим числом GET-параметров; 0 — только без параметров. |
| `crawl.max_urls_per_subdomain` | `int \| None` | — | С all_subdomains: не больше стольких URL с одного поддомена. |
| `crawl.path_limits` | `list[tuple[str, int]]` | `[]` | Лимиты по разделам: пары [регулярное выражение, максимум URL]; URL сверх лимита не обходятся. |
| `crawl.concurrency` | `int` | `20` | Сколько запросов к сайту выполняется одновременно. |
| `crawl.max_rps` | `float \| None` | — | Не больше стольких запросов в секунду; не задано — без ограничения. |
| `crawl.timeout_s` | `float` | `20` | Сколько секунд ждать ответа, прежде чем считать URL неответившим. |
| `crawl.http_client` | `Literal['impit', 'curl']` | `"impit"` | HTTP-клиент: impit — по умолчанию, самый быстрый; curl — запасной (curl-impersonate, `rb-spider[curl]`), если сайт плохо отвечает impit. |
| `crawl.retries_5xx` | `int` | `0` | Сколько раз повторять запрос, ответивший 5xx, прежде чем записать ошибку. |
| `crawl.retries_no_response` | `int` | `2` | Сколько раз повторить URL, который не ответил вовсе (таймаут, обрыв соединения, ошибка TLS), прежде чем записать его неответившим; каждый повтор — после паузы crawl.retry_pause_s. Сверх этого HTTP-клиент сам повторяет запрос один раз сразу. |
| `crawl.retry_pause_s` | `float` | `5.0` | Пауза перед повтором неответившего URL, секунды; растёт с каждой попыткой (5, 10, 15…). |
| `crawl.cookies` | `Literal['session', 'none']` | `"session"` | Cookies: session — хранить в пределах обхода (как браузер); none — не хранить и не слать. |
| `crawl.assume_html` | `bool` | `true` | Ответ без Content-Type разбирать как HTML. |
| `crawl.ca_bundle` | `str \| None` | — | Свой корневой сертификат (PEM) — для MITM-прокси и корпоративных сетей; только с http_client = curl (impit свой CA не загружает — там только verify_tls = false). |
| `crawl.auth` | `Literal['none', 'basic']` | `"none"` | HTTP-авторизация сайта: basic — заголовок Authorization к URL сайта (не к чужим); пароль — `spider auth login --provider site`. |
| `crawl.auth_user` | `str \| None` | — | Логин для auth = basic. |
| `crawl.verify_tls` | `bool` | `true` | Проверять сертификат HTTPS; false — принимать и самоподписанные / просроченные (тестовые стенды). |
| `crawl.respect_hsts` | `bool` | `true` | Как браузер: после ответа с Strict-Transport-Security http-ссылки на тот же хост не скачивать, а записывать как 307 на https-адрес (HSTS Policy); false — скачивать и видеть настоящий редирект. |
| `crawl.render` | `Literal['never', 'always', 'auto']` | `"never"` | JS-рендеринг: never — SEO-данные из HTML ответа сервера; always — HTML-страницы с кодом 200 ещё и открываются в браузере (Playwright, `rb-spider[render]`), данные — из DOM после выполнения JS; auto — первые render_auto_sample HTML-страниц рендерятся, и если JS ни на одной ничего не поменял (ссылки, текст, title, description, h1, canonical, robots), остальные читаются без браузера. |
| `crawl.render_auto_sample` | `int` | `20` | Сколько первых HTML-страниц отрендерить при render = auto, чтобы решить, нужен ли JS. |
| `crawl.render_viewport` | `str` | `"desktop"` | Размер окна браузера при рендеринге (Window Size): desktop — 1366×768, mobile — 411×731 как у Googlebot Smartphone (сенсорный экран), или ШИРИНАxВЫСОТА, например 1920x1080. |
| `crawl.render_console` | `bool` | `true` | Записывать ошибки и предупреждения консоли браузера при рендеринге (JavaScript Error Reporting). |
| `crawl.render_flatten_shadow_dom` | `bool` | `true` | Читать содержимое Shadow DOM веб-компонентов как часть страницы (Flatten Shadow DOM). |
| `crawl.render_flatten_iframes` | `bool` | `true` | Читать содержимое iframe как часть страницы, на которой он стоит (Flatten iframes). |
| `crawl.render_screenshots` | `bool` | `false` | Скриншот каждой отрендеренной страницы (первый экран, JPEG) — папка рядом с базой, путь в spider_pages.screenshot и `spider url`; ~30–100 КБ на страницу. |
| `crawl.render_images` | `bool` | `false` | Загружать картинки в браузере при рендеринге: медленнее, зато видны реальные и отображаемые размеры картинок (Image Details, «Images: Incorrectly Sized Images»); по умолчанию картинки не грузятся. |
| `crawl.render_tabs` | `int` | `4` | Сколько вкладок браузера открыто одновременно при рендеринге. |
| `crawl.render_wait_ms` | `int` | `0` | Сколько миллисекунд ещё ждать скрипты после загрузки страницы (AJAX) при рендеринге. |
| `crawl.render_browser` | `str \| None` | — | Путь к браузеру (Chromium / Chrome) для рендеринга; не задано — сборка Playwright, иначе самая свежая из кэша Playwright (ms-playwright), иначе установленный Google Chrome. |
| `crawl.parse_workers` | `int \| None` | — | Сколько отдельных процессов разбирают HTML на больших обходах; 0 — всё в основном процессе; не задано — по числу ядер, не больше 4. |
| `crawl.user_agent` | `str \| None` | — | User-Agent запросов: своя строка или пресет — googlebot, googlebot-smartphone, bingbot, yandexbot, chrome; не задано — как у обычного браузера (Firefox). |
| `crawl.headers` | `dict[str, str]` | `{}` | Дополнительные заголовки каждого запроса. |
| `crawl.fingerprint` | `str \| None` | — | Отпечаток браузера из файла (JSON сервиса отпечатков): имя в папке отпечатков пользователя (`spider fingerprints list`) или путь. Один на весь обход: User-Agent, Accept-Language и sec-ch-ua* всех запросов, а в браузере рендеринга — navigator, экран, WebGL, часовой пояс, локаль, WebRTC выключен. Явные crawl.user_agent и crawl.headers важнее. |
| `crawl.fingerprint_timezone` | `Literal['ip', 'file']` | `"ip"` | Часовой пояс браузера с отпечатком: ip — как у выходного IP (ipinfo.io через прокси; при старте и после каждой смены IP — модем мог оказаться в другом регионе), file — как в файле отпечатка. |
| `crawl.fingerprint_check` | `Literal['warn', 'stop', 'off']` | `"warn"` | Перед обходом сверить отпечаток: одна ли в нём ОС (User-Agent, platform, видеокарта, шрифты, TCP прокси), совпадает ли с ОС машины при рендеринге и со страной, часовым поясом и языком выходного IP (запрос к ipinfo.io через прокси). warn — предупредить, stop — не начинать (код 2), off — не сверять. |
| `crawl.robots` | `Literal['respect', 'ignore', 'report']` | `"respect"` | robots.txt: respect — запрещённое не скачивать (но показать в отчёте), с учётом Crawl-delay; ignore — не читать; report — скачивать всё, но отмечать запрещённое. |
| `crawl.robots_custom` | `str \| None` | — | Свой robots.txt для сайта вместо настоящего — проверить правки до выкладки (текст файла). |
| `crawl.robots_show_internal_blocked` | `bool` | `true` | Записывать в отчёт URL сайта, запрещённые robots.txt. |
| `crawl.robots_show_external_blocked` | `bool` | `true` | Записывать в отчёт чужие URL, запрещённые их robots.txt. |
| `crawl.robots_user_agent` | `str \| None` | — | От чьего имени читать robots.txt; не задано — от User-Agent запросов. |
| `crawl.proxy_urls` | `list[str]` | `[]` | Прокси для всего трафика к сайтам: страницы, robots.txt, XML sitemap, браузер рендеринга; как их использовать — crawl.proxy_mode. Браузеру нужен HTTP-адрес (SOCKS5 с паролем Chromium не умеет) — ставьте его первым. Пароль не пишите в файл: `{password}` в адресе заменится секретом из `spider auth login --provider proxy` (или переменной SPIDER_PROXY_API_KEY). Перед обходом и `spider fetch` каждый адрес проверяется: TCP-соединение (crawl.proxy_connect_timeout_s), затем запрос robots.txt сайта через прокси и тот же запрос напрямую, одновременно. Через прокси нет ответа, а напрямую есть — прокси не работает; нет ответа и напрямую — это сбой сайта, прокси не виноват. |
| `crawl.proxy_mode` | `Literal['rotate', 'failover']` | `"rotate"` | rotate — страницы чередуют адреса crawl.proxy_urls по запросам (sitemap и браузер — через первый); failover — всё идёт через первый рабочий адрес, следующий — запасной, когда этот умер (у мобильного прокси — HTTP- и SOCKS5-вход одного модема). |
| `crawl.proxy_fallback` | `Literal['stop', 'direct']` | `"stop"` | Прокси не работает (проверка перед стартом или после crawl.proxy_max_failures запросов без ответа): stop — остановиться (обход продолжается `spider crawls resume`), direct — идти дальше без прокси, сайт увидит ваш IP. В терминале при stop перед стартом spider спросит, продолжить ли без прокси. |
| `crawl.proxy_max_failures` | `int` | `3` | Сколько запросов через прокси подряд, без единого ответа (ошибка прокси или таймаут), запускают проверку прокси против прямого запроса к тому же сайту. Прокси не ответил, а сайт напрямую ответил — адрес умер: failover — на следующий адрес, дальше — crawl.proxy_fallback; сайт не ответил и напрямую — счёт с нуля, обход идёт дальше. Любой ответ через прокси тоже обнуляет счёт. |
| `crawl.proxy_connect_timeout_s` | `float` | `5` | Сколько секунд ждать TCP-соединения с самим прокси при проверке. Не открылось за это время, отказ, имя не нашлось — адрес не работает сразу, без запроса через него. |
| `crawl.proxy_state_ttl_s` | `float` | `600` | Сколько секунд spider помнит, жив ли адрес прокси, между запусками (файл proxy-state.json в SPIDER_CACHE_DIR). Проверка моложе этого срока: мёртвый адрес не проверяется, а сразу уступает место crawl.proxy_fallback (failover — следующему адресу, который не известен как мёртвый); живой проверка перед стартом пропускает (обрыв посреди обхода всё равно ловится по crawl.proxy_max_failures). Старше или нет записи — адрес проверяется, запись обновляется. 0 — не помнить, проверять каждый запуск. Состояние видно в `spider doctor`, проверить сейчас — `spider auth status --check`. |
| `crawl.proxy_change_ip_urls` | `list[str]` | `[]` | Ссылки смены IP прокси (мобильный прокси): когда сайт блокирует (crawl.proxy_change_ip_on), spider открывает их по очереди, пока одна не ответит «ok», ждёт, пока прокси снова ответит, и повторяет заблокированные запросы. Не прошли проверку все адреса перед стартом — spider один раз меняет IP, ждёт прокси (crawl.proxy_change_ip_wait_s) и проверяет снова; отказ провайдера попадает в текст ошибки. Ключ не пишите в файл: `{key}` заменится секретом из `spider auth login --provider proxy_key` (или переменной SPIDER_PROXY_KEY_API_KEY). |
| `crawl.proxy_change_ip_on` | `list[int]` | `[403, 429]` | Коды ответа, которые значат «сайт заблокировал IP» и меняют его (crawl.proxy_change_ip_urls). |
| `crawl.proxy_change_ip_min_interval_s` | `float` | `10` | Не менять IP чаще, чем раз в столько секунд (лимит провайдера, переподключение модема). |
| `crawl.proxy_change_ip_wait_s` | `float` | `60` | Сколько секунд после смены IP ждать, пока прокси снова ответит. |
| `crawl.proxy_change_ip_max` | `int` | `100` | Не больше стольких смен IP за обход. Смена прекращается и раньше — после трёх смен подряд, на которые сайт отвечал только блоком: тогда ответы с блоком записываются как есть. |
| `crawl.store_html` | `bool` | `false` | Сохранять HTML страниц (сжатым, в отдельный файл рядом с базой); иначе только md5. |
| `collect.internal_links.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.internal_links.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.external_links.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.external_links.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.canonicals.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.canonicals.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.meta_refresh.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.meta_refresh.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.images.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.images.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.hreflang.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.hreflang.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.pagination.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.pagination.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.mobile_alternate.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.mobile_alternate.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.link_path` | `bool` | `false` | Хранить у каждой ссылки путь её предков (/nav.menu/…) — для разбора зон; ~40 байт на ссылку. |
| `collect.uncrawlable_links` | `bool` | `false` | Хранить и «ссылки», по которым не перейти (javascript:, href не у <a>, onclick) — видны в `spider links`. |
| `collect.html_validation` | `bool` | `true` | Проверять структуру HTML по исходному коду: <head> / <body>, порядок, элементы в <head>. |
| `collect.images_srcset` | `bool` | `false` | Брать картинки и из атрибута srcset, а не только src. |
| `collect.structured_data` | `list[Literal['json-ld', 'microdata', 'rdfa']]` | `[]` | Какую микроразметку извлекать и проверять (Schema.org, расширенные результаты Google): json-ld, microdata, rdfa; пусто — не извлекать. Microdata и RDFa — extra `rb-spider[structured]`. |
| `collect.near_duplicates` | `bool` | `false` | Считать подписи MinHash текста страниц — для проверки «Content: Near Duplicates» (extra `rb-spider[near]`; ~0,7 КБ на страницу). |
| `collect.css.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.css.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.js.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.js.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.media.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.media.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.iframes.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.iframes.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `sitemaps.crawl` | `bool` | `false` | Читать XML sitemap сайта (extra `rb-spider[sitemaps]`): проверки Sitemaps, `spider sitemaps`. Файлы качаются с User-Agent, timeout и прокси обхода. |
| `sitemaps.discover` | `bool` | `true` | Искать sitemap сам: строки Sitemap: в robots.txt, затем /sitemap.xml и т.п. |
| `sitemaps.urls` | `list[str]` | `[]` | Адреса sitemap (или индексов) вдобавок к найденным. |
| `sitemaps.follow` | `bool` | `true` | Обходить URL из sitemap, даже если на них нет ссылок (иначе — только сравнивать). |
| `export.presets` | `dict[str, list[str]]` | `{ "audit" = ["pages", "issues", "links"], "links" = ["links", "links:links_no_anchor_text", "links:links_internal_nofollow_outlinks", "links:internal_client_error"], "full" = ["pages", "links", "issues", "queued", "headers", "cookies", "source", "text", "duplicates", "custom", "sitemap-urls", "javascript", "rendered-source", "screenshots", "lighthouse"] }` | Пресеты выгрузки: имя → список наборов (pages, links, issues, queued, headers, cookies, source, text, duplicates, custom, sitemap-urls, javascript, rendered-source, screenshots, lighthouse); `набор:код` — только находки / ссылки / URL одной проверки, например `issues:page_title_missing`, `links:links_no_anchor_text`. |
| `compare.fields` | `list[str]` | `["indexability", "status_code", "title", "meta_description", "h1", "h2", "canonical", "directives", "word_count", "content", "depth", "inlinks", "unique_inlinks", "internal_outlinks", "unique_outlinks", "external_outlinks", "structured_data_types"]` | Поля Change Detection: indexability, status_code, title, meta_description, h1, h2, canonical, directives, word_count, content, depth, inlinks, unique_inlinks, internal_outlinks, unique_outlinks, external_outlinks, structured_data_types (content — HTML изменился, по md5). |
| `compare.url_mapping` | `list[rb_spider.core.settings.UrlMapping]` | `[]` | URL Mapping: правила «регулярное выражение → замена» для URL прежнего обхода, чтобы сравнить разные адреса одних страниц — staging против production, переезд на другой домен или HTTPS, новая структура URL. Применяются по порядку. |
| `custom.search` | `list[rb_spider.core.settings.CustomSearch]` | `[]` | Поиски по страницам: [[custom.search]] с name, query, regex, scope (html / text / element). |
| `custom.extract` | `list[rb_spider.core.settings.CustomExtract]` | `[]` | Извлечения: [[custom.extract]] с name, kind (css / xpath / regex), query, output, limit. |
| `custom.link_positions` | `list[tuple[str, str]]` | `[["nav", "nav"], ["menu", "nav"], ["header", "header"], ["footer", "footer"], ["aside", "sidebar"], ["sidebar", "sidebar"]]` | Зоны ссылок: пары [слово пути, зона] по порядку — слово класса, id или тега предка ссылки; ни одно не подошло — content. |
| `rewrite.remove_params` | `list[str]` | `[]` | Удалять из найденных URL эти GET-параметры (точное имя, с учётом регистра). |
| `rewrite.regex` | `list[tuple[str, str]]` | `[]` | Замены по регулярным выражениям, по порядку: пары [выражение, замена]; группы в замене — \1, \2. |
| `rewrite.lowercase` | `bool` | `false` | Переводить найденные URL в нижний регистр целиком. |
| `rewrite.percent_encoding` | `Literal['keep', 'upper', 'lower']` | `"keep"` | Регистр шестнадцатеричных цифр в %-кодировании (%D0 или %d0): keep — как на странице. |
| `lighthouse.source` | `Literal['local', 'psi']` | `"local"` | Кто замеряет: local — Lighthouse на этой машине (работает и за авторизацией, и на локальном сайте); psi — PageSpeed Insights API: те же аудиты с серверов Google плюс данные реальных пользователей (CrUX), только для публичных страниц; нужен extra `gsc` и ключ `gsc auth login --provider pagespeed`. |
| `lighthouse.psi_concurrency` | `int` | `4` | Сколько страниц PageSpeed Insights замеряет одновременно (source = psi). |
| `lighthouse.command` | `str` | `"lighthouse"` | Как запускать Lighthouse: команда из PATH (`npm install -g lighthouse`) или, например, "npx --yes lighthouse" — без установки. |
| `lighthouse.strategy` | `Literal['mobile', 'desktop']` | `"mobile"` | Мобильный (как Googlebot Smartphone) или десктопный замер; mobile — ещё и замеры Mobile. |
| `lighthouse.per_template` | `int` | `1` | Сколько страниц брать на шаблон, когда URL не заданы: шаблон — папка и глубина пути (все /catalog/x/y — один), страницы — с наибольшим числом входящих ссылок; главная — всегда. |
| `lighthouse.max_pages` | `int` | `20` | Не больше стольких страниц выборки за запуск. |
| `lighthouse.timeout_s` | `int` | `120` | Сколько секунд ждать Lighthouse на одной странице. |
| `lighthouse.chrome` | `str \| None` | — | Путь к Chrome / Chromium для Lighthouse; не задано — crawl.render_browser, иначе Chromium из кэша Playwright, иначе установленный Chrome. |
| `thresholds.redirect_chain_hops` | `int` | `2` | Со скольких прыжков редирект считается цепочкой (Internal Redirect Chain). |
| `thresholds.title_max_chars` | `int` | `60` | Title длиннее — «Page Titles: Over … Characters». |
| `thresholds.title_min_chars` | `int` | `30` | Title короче — «Page Titles: Below … Characters». |
| `thresholds.description_max_chars` | `int` | `155` | Meta description длиннее — «Meta Description: Over … Characters». |
| `thresholds.description_min_chars` | `int` | `70` | Meta description короче — «Meta Description: Below … Characters». |
| `thresholds.title_max_px` | `int` | `561` | Title шире стольких пикселей в выдаче — «Page Titles: Over … Pixels». |
| `thresholds.title_min_px` | `int` | `200` | Title уже — «Page Titles: Below … Pixels». |
| `thresholds.description_max_px` | `int` | `985` | Meta description шире (в сумме по строкам сниппета) — «Meta Description: Over … Pixels». |
| `thresholds.description_min_px` | `int` | `400` | Meta description уже — «Meta Description: Below … Pixels». |
| `thresholds.serp_title_font_px` | `float` | `20` | Кегль title в выдаче Google (Arial), по нему считаются пиксели. |
| `thresholds.serp_description_font_px` | `float` | `14` | Кегль сниппета в выдаче Google (Arial), по нему считаются пиксели description. |
| `thresholds.h1_max_chars` | `int` | `70` | H1 длиннее — «H1: Over … Characters». |
| `thresholds.h2_max_chars` | `int` | `70` | H2 длиннее — «H2: Over … Characters». |
| `thresholds.low_content_words` | `int` | `200` | Меньше слов в видимом тексте — «Content: Low Content Pages». |
| `thresholds.image_kb` | `int` | `100` | Картинка тяжелее стольких КБ — «Images: Over … KB». |
| `thresholds.alt_max_chars` | `int` | `100` | Alt длиннее — «Images: Alt Text Over … Characters». |
| `thresholds.crawl_depth` | `int` | `4` | Страницы на такой глубине и глубже — «Links: High Crawl Depth». |
| `thresholds.internal_outlinks` | `int` | `1000` | Больше внутренних follow-ссылок — «Links: High Internal Outlinks». |
| `thresholds.external_outlinks` | `int` | `10` | Больше внешних follow-ссылок — «Links: High External Outlinks». |
| `thresholds.non_descriptive_anchors` | `list[str]` | `["click here", "here", "read more", "more", "learn more", "link", "подробнее", "читать далее", "далее", "здесь", "тут", "ссылка", "перейти", "узнать больше"]` | Анкоры, ничего не говорящие о цели (без учёта регистра) — «Links: Non-Descriptive Anchor Text». |
| `thresholds.url_max_chars` | `int` | `115` | URL длиннее — «URL: Over … Characters». |
| `thresholds.duplicates_indexable_only` | `bool` | `true` | Искать дубли (точные, почти-дубли, title и т.д.) только среди индексируемых страниц. |
| `thresholds.near_duplicate_similarity` | `int` | `90` | С какого сходства текста (%) страницы — почти-дубли (MinHash). |
| `thresholds.readability_difficult` | `float` | `50` | Индекс Флеша ниже — «Content: Readability Difficult» (для русского — формула Оборневой). |
| `thresholds.readability_very_difficult` | `float` | `30` | Индекс Флеша ниже — «Content: Readability Very Difficult». |
| `thresholds.readability_min_words` | `int` | `100` | Читаемость оценивается у страниц хотя бы со стольких слов текста. |
| `thresholds.soft_404_patterns` | `list[str]` | `["\\b404\\b", "not found", "page (does not|doesn't|no longer) exist", "не найден", "не существует", "нет такой страницы", "страница удалена"]` | Регулярные выражения (без учёта регистра) по title и H1 страницы с кодом 200: совпало — «Content: Soft 404 Pages». |
| `thresholds.document_max_mb` | `float` | `2` | HTML-страница больше стольких МБ — «Validation: HTML Document Over 2MB» (Googlebot читает 2 МБ). |
| `thresholds.resource_max_mb` | `float` | `2` | JS / CSS больше стольких МБ — «Validation: Resource Over 2MB». |
| `thresholds.image_oversize_ratio` | `float` | `2` | Картинка шире или выше, чем показана на странице, больше чем во столько раз — «Images: Incorrectly Sized Images» (2 — запас на экраны высокой плотности). |
| `thresholds.js_content_min_words` | `int` | `10` | После JS на странице хотя бы столько новых слов — «JavaScript: Contains JavaScript Content». |
| `thresholds.sitemap_max_urls` | `int` | `50000` | Больше URL в одном файле sitemap — «Sitemaps: Over 50k URLs». |
| `thresholds.sitemap_max_mb` | `float` | `50` | Файл sitemap больше стольких МБ (без сжатия) — «Sitemaps: Over 50mb». |
| `thresholds.issues_indexable_only` | `bool` | `false` | Проверки контента (title, description, H1, H2, Content…) только для индексируемых страниц — Ignore Non-Indexable URLs for Issues. |
| `thresholds.self_refresh_non_indexable` | `bool` | `true` | Страница с meta / HTTP Refresh на саму себя — неиндексируемая (Redirected). |
| `thresholds.ignore_paginated_duplicates` | `bool` | `true` | Не считать дублями title / description / H1 / H2 страниц пагинации 2+ (с rel=prev): у страниц одного списка они обычно одинаковы. |
| `thresholds.internal_search` | `list[str]` | `["[?&](q|s|query|search|text|keyword|keywords)=", "/(search|poisk|find)(/|$|\\?)"]` | Регулярные выражения (без учёта регистра) по пути и параметрам URL: совпало — страница внутреннего поиска, «URL: Internal Search». |
<!-- keys:end -->

## Рецепты

Рецепт — готовый профиль под типичную задачу. Все, кроме прокси, встроены: `spider crawl <url> --profile <имя>`. Свой вариант на основе рецепта — `spider profiles init my --from <имя>`: в файле будут все ключи с описаниями. Итог настроек до обхода — `spider config show --profile <имя>`.

| Задача | Как запустить | Что смотреть после |
| --- | --- | --- |
| Быстрый первый взгляд | `spider crawl <url> --profile quick-audit` | `spider issues` |
| Миграция: старые URL → новые | `spider crawl --list old-urls.txt --profile migration` | `spider redirects --only errors`, `spider urls --issue internal_client_error` |
| Сайт на JavaScript | `spider crawl <url> --profile js-site` (нужен `rb-spider[render]`) | `spider issues`; `spider_pages.rendered = 0` в `spider query` — где рендер не удался |
| Только битые ссылки | `spider crawl <url> --profile broken-links` | `spider export links --status 4xx`, `spider export links --status 5xx` |
| Большой интернет-магазин | `spider crawl <url> --profile big-shop --detach` | `spider status`, затем `spider issues` |
| Обход через прокси | свой профиль, пример ниже | как обычно |

### Обход через прокси

Адрес прокси у каждого свой, поэтому это не встроенный профиль, а пример своего профиля для всех проектов: `spider profiles init proxy --user`, затем поправить файл. Пароль в файл не пишется: `{password}` подставляется из системного хранилища ключей — один раз `spider auth login --provider proxy`. Без `--profile proxy` обход идёт напрямую.

```toml
description = "Обход через прокси: запросы чередуются между адресами"
extends = "default"

[crawl]
proxy_urls = ["http://user:{password}@proxy1.example:8000", "http://user:{password}@proxy2.example:8000"]
concurrency = 10
proxy_fallback = "stop"      # прокси умер (не оплачен, модем выключен): stop — остановиться, direct — без прокси
```

Мобильный прокси — один модем с двумя входами (HTTP и SOCKS5) и ссылками смены IP. Входы — `failover`: всё через первый, второй — запасной; IP меняется, когда сайт блокирует (403, 429), и заблокированные запросы повторяются. Ключ ссылки — `{key}`, один раз `spider auth login --provider proxy_key`:

```toml
description = "Мобильный прокси: смена IP при блокировке"
extends = "default"

[crawl]
proxy_urls = ["http://user:{password}@mproxy.example:25580", "socks5h://user:{password}@bproxy.example:25580"]
proxy_mode = "failover"
fingerprint = "phone-1"      # spider fingerprints add / new — один на весь обход
proxy_change_ip_urls = [
  "https://changeip.example/?proxy_key={key}&format=json",
  "https://changeip-backup.example/?proxy_key={key}&format=json",
]
concurrency = 5
```

На сервере без keychain (Linux) вместо `auth login` — переменные окружения `SPIDER_PROXY_API_KEY` (пароль) и `SPIDER_PROXY_KEY_API_KEY` (ключ смены IP); они важнее keychain. Новый прокси — поправить адреса в профиле и снова `auth login` (или новые значения переменных).

Отпечаток (`crawl.fingerprint`) — вторая половина «личности»: файл сервиса отпечатков (`spider fingerprints add FILE --name NAME`) или сгенерированный (`spider fingerprints new NAME --os android --chrome 155`). Он одинаков весь обход: заголовки каждого запроса (User-Agent, Accept-Language, sec-ch-ua*) и то, что видит скрипт сайта в браузере; при смене IP начинается новый «посетитель» (cookies) с тем же отпечатком. Согласованность: одна ОС в отпечатке и у TCP прокси (выставляется у провайдера), страна и язык — как у выходного IP, а часовой пояс браузер по умолчанию берёт у самого IP (`crawl.fingerprint_timezone = ip`: мобильный IP часто в другом регионе, чем написано в файле, — и меняет его после каждой смены IP); проверка — `spider fingerprints check NAME --profile …` и перед каждым обходом (`crawl.fingerprint_check`). У мобильного прокси естественнее всего отпечаток Android. Рендеринг берёт шрифты и canvas у машины: на Linux-сервере с отпечатком Windows/macOS/Android обходите без него.

Через прокси идёт весь трафик к сайту: страницы, robots.txt, XML sitemap и браузер (`render`); sitemap и браузер — через первый адрес, браузеру нужен HTTP-адрес (SOCKS5 с паролем Chromium не умеет). Перед стартом каждый адрес проверяется за секунды: TCP-соединение с прокси (`crawl.proxy_connect_timeout_s`), затем robots.txt через прокси и напрямую — прокси виноват, только если сайт напрямую отвечает. Все адреса мёртвые и заданы `crawl.proxy_change_ip_urls` — один раз смена IP и проверка снова; отказ провайдера (не оплачен, неверный ключ) — в тексте ошибки. Не работает — `PROXY_UNAVAILABLE` (код 5) и `spider crawls resume`, когда оживёт; в терминале spider сначала спросит, идти ли без него. Посреди обхода и `spider fetch` — та же проверка после `crawl.proxy_max_failures` запросов подряд без ответа через прокси (ошибка прокси или таймаут). Результат проверки spider помнит между запусками (`crawl.proxy_state_ttl_s`, файл `proxy-state.json` в кэше пользователя или `SPIDER_CACHE_DIR`): адрес, проверенный недавно, не проверяется снова — мёртвый сразу уступает место `crawl.proxy_fallback` (у failover — следующему адресу, который не известен как мёртвый), живой пропускает проверку перед стартом. Состояние адресов видно в `spider doctor`, проверить сейчас — `spider auth status --check`.

## Встроенные профили

Генерируется из файлов профилей в пакете (тест сверяет с кодом, каждый блок проходит `spider config validate`).

<!-- profiles:begin (generated from the built-in profiles) -->
### `default`

Значения по умолчанию: браузерный User-Agent, соблюдать robots.txt, 20 запросов одновременно

```toml
description = "Значения по умолчанию: браузерный User-Agent, соблюдать robots.txt, 20 запросов одновременно"
```

### `big-shop`

Большой магазин: без сортировок, фильтров и utm-меток, без проверки тысяч картинок товаров

```toml
description = "Большой магазин: без сортировок, фильтров и utm-меток, без проверки тысяч картинок товаров"
extends = "default"

[crawl]
exclude = ["[?&](sort|order|dir|filter|limit|view|page_size)=", "[?&]utm_[a-z]+="]
max_links_per_page = 1000

[collect.images]
follow = false

[collect.external_links]
store = false
```

### `broken-links`

Поиск битых ссылок и ресурсов: проверить все ссылки, картинки, CSS и JS, в том числе на чужие сайты

```toml
description = "Поиск битых ссылок и ресурсов: проверить все ссылки, картинки, CSS и JS, в том числе на чужие сайты"
extends = "default"

[crawl]
concurrency = 30
follow_external_nofollow = true

[collect.canonicals]
follow = false
```

### `fast`

Быстрый аудит своего сайта: 50 запросов одновременно (на чужих сайтах — осторожно)

```toml
description = "Быстрый аудит своего сайта: 50 запросов одновременно (на чужих сайтах — осторожно)"
extends = "default"

[crawl]
concurrency = 50
```

### `googlebot`

Обход глазами Googlebot для смартфонов (как Google индексирует сайт в mobile-first)

```toml
description = "Обход глазами Googlebot для смартфонов (как Google индексирует сайт в mobile-first)"
extends = "default"

[crawl]
user_agent = "googlebot-smartphone"
```

### `js-site`

Сайт на JavaScript (SPA): страницы рендерятся браузером, данные — из готового DOM (нужен rb-spider[render])

```toml
description = "Сайт на JavaScript (SPA): страницы рендерятся браузером, данные — из готового DOM (нужен rb-spider[render])"
extends = "default"

[crawl]
render = "always"
render_tabs = 4
render_wait_ms = 1000
concurrency = 10
```

### `migration`

Миграция: только URL из списка (spider crawl --list old.txt) и их редиректы до конца

```toml
description = "Миграция: только URL из списка (spider crawl --list old.txt) и их редиректы до конца"
extends = "default"

[crawl]
mode = "list"

[collect.canonicals]
follow = false

[collect.images]
follow = false

[collect.css]
follow = false

[collect.js]
follow = false
```

### `quick-audit`

Быстрый первый взгляд на сайт: до 1000 URL, без проверки внешних ссылок и ресурсов

```toml
description = "Быстрый первый взгляд на сайт: до 1000 URL, без проверки внешних ссылок и ресурсов"
extends = "default"

[crawl]
max_urls = 1000

[collect.external_links]
follow = false

[collect.images]
follow = false

[collect.css]
follow = false

[collect.js]
follow = false
```

### `yandexbot`

Обход глазами основного робота Яндекса

```toml
description = "Обход глазами основного робота Яндекса"
extends = "default"

[crawl]
user_agent = "yandexbot"
```
<!-- profiles:end -->
