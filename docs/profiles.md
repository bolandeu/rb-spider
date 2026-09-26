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
| `crawl.follow_internal_nofollow` | `bool` | `false` | Обходить внутренние ссылки с rel=nofollow. |
| `crawl.follow_external_nofollow` | `bool` | `false` | Проверять внешние ссылки с rel=nofollow. |
| `crawl.content_exclude` | `list[str]` | `["nav", "footer"]` | CSS-селекторы блоков, которые не считаются текстом страницы (число слов, «Lorem ipsum»). |
| `crawl.concurrency` | `int` | `20` | Сколько запросов к сайту выполняется одновременно. |
| `crawl.max_rps` | `float \| None` | — | Не больше стольких запросов в секунду; не задано — без ограничения. |
| `crawl.timeout_s` | `float` | `20` | Сколько секунд ждать ответа, прежде чем считать URL неответившим. |
| `crawl.http_client` | `Literal['impit', 'curl']` | `"impit"` | HTTP-клиент: impit — по умолчанию, самый быстрый; curl — запасной (curl-impersonate, `rb-spider[curl]`), если сайт плохо отвечает impit. |
| `crawl.verify_tls` | `bool` | `true` | Проверять сертификат HTTPS; false — принимать и самоподписанные / просроченные (тестовые стенды). |
| `crawl.respect_hsts` | `bool` | `true` | Как браузер: после ответа с Strict-Transport-Security http-ссылки на тот же хост не скачивать, а записывать как 307 на https-адрес (HSTS Policy); false — скачивать и видеть настоящий редирект. |
| `crawl.render` | `Literal['never', 'always']` | `"never"` | JS-рендеринг: never — SEO-данные из HTML ответа сервера; always — HTML-страницы с кодом 200 ещё и открываются в браузере (Playwright, `rb-spider[render]`), данные — из DOM после выполнения JS. |
| `crawl.render_tabs` | `int` | `4` | Сколько вкладок браузера открыто одновременно при render = always. |
| `crawl.render_wait_ms` | `int` | `0` | Сколько миллисекунд ещё ждать скрипты после загрузки страницы (AJAX) при render = always. |
| `crawl.render_browser` | `str \| None` | — | Путь к браузеру (Chromium / Chrome) для render = always; не задано — сборка Playwright, иначе самая свежая из кэша Playwright (ms-playwright), иначе установленный Google Chrome. |
| `crawl.parse_workers` | `int \| None` | — | Сколько отдельных процессов разбирают HTML на больших обходах; 0 — всё в основном процессе; не задано — по числу ядер, не больше 4. |
| `crawl.user_agent` | `str \| None` | — | User-Agent запросов: своя строка или пресет — googlebot, googlebot-smartphone, bingbot, yandexbot, chrome; не задано — как у обычного браузера (Firefox). |
| `crawl.headers` | `dict[str, str]` | `{}` | Дополнительные заголовки каждого запроса. |
| `crawl.robots` | `Literal['respect', 'ignore', 'report']` | `"respect"` | robots.txt: respect — запрещённое не скачивать (но показать в отчёте), с учётом Crawl-delay; ignore — не читать; report — скачивать всё, но отмечать запрещённое. |
| `crawl.robots_user_agent` | `str \| None` | — | От чьего имени читать robots.txt; не задано — от User-Agent запросов. |
| `crawl.proxy_urls` | `list[str]` | `[]` | Прокси, чередуются по запросам. Пароль не пишите в файл: `{password}` в адресе заменится секретом из `spider auth login --provider proxy`. |
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
| `collect.images_srcset` | `bool` | `false` | Брать картинки и из атрибута srcset, а не только src. |
| `collect.near_duplicates` | `bool` | `false` | Считать подписи MinHash текста страниц — для проверки «Content: Near Duplicates» (extra `rb-spider[near]`; ~0,7 КБ на страницу). |
| `collect.css.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.css.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.js.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.js.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.media.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.media.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.iframes.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.iframes.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `rewrite.remove_params` | `list[str]` | `[]` | Удалять из найденных URL эти GET-параметры (точное имя, с учётом регистра). |
| `rewrite.regex` | `list[tuple[str, str]]` | `[]` | Замены по регулярным выражениям, по порядку: пары [выражение, замена]; группы в замене — \1, \2. |
| `rewrite.lowercase` | `bool` | `false` | Переводить найденные URL в нижний регистр целиком. |
| `rewrite.percent_encoding` | `Literal['keep', 'upper', 'lower']` | `"keep"` | Регистр шестнадцатеричных цифр в %-кодировании (%D0 или %d0): keep — как на странице. |
| `thresholds.redirect_chain_hops` | `int` | `2` | Со скольких прыжков редирект считается цепочкой (Internal Redirect Chain). |
| `thresholds.title_max_chars` | `int` | `60` | Title длиннее — «Page Titles: Over … Characters». |
| `thresholds.title_min_chars` | `int` | `30` | Title короче — «Page Titles: Below … Characters». |
| `thresholds.description_max_chars` | `int` | `155` | Meta description длиннее — «Meta Description: Over … Characters». |
| `thresholds.description_min_chars` | `int` | `70` | Meta description короче — «Meta Description: Below … Characters». |
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
| `thresholds.ignore_paginated_duplicates` | `bool` | `true` | Не считать дублями title / description / H1 / H2 страниц пагинации 2+ (с rel=prev): у страниц одного списка они обычно одинаковы. |
| `thresholds.internal_search` | `list[str]` | `["[?&](q|s|query|search|text|keyword|keywords)=", "/(search|poisk|find)(/|$|\\?)"]` | Регулярные выражения (без учёта регистра) по пути и параметрам URL: совпало — страница внутреннего поиска, «URL: Internal Search». |
<!-- keys:end -->

## Рецепты

Рецепт — готовый профиль под типичную задачу. Все, кроме прокси, встроены: `spider crawl <url> --profile <имя>`. Свой вариант на основе рецепта — `spider profiles init my --from <имя>`: в файле будут все ключи с описаниями. Итог настроек до обхода — `spider config show --profile <имя>`.

| Задача | Как запустить | Что смотреть после |
| --- | --- | --- |
| Быстрый первый взгляд | `spider crawl <url> --profile quick-audit` | `spider issues` |
| Миграция: старые URL → новые | `spider crawl --list old-urls.txt --profile migration` | `spider redirects --only errors`, `spider urls --issue internal_client_error` |
| Сайт на JavaScript | `spider crawl <url> --profile js-site` (нужен `rb-spider[render]`) | `spider issues`; `pages.rendered = 0` в `spider query` — где рендер не удался |
| Только битые ссылки | `spider crawl <url> --profile broken-links` | `spider export links --status 4xx`, `spider export links --status 5xx` |
| Большой интернет-магазин | `spider crawl <url> --profile big-shop --detach` | `spider status`, затем `spider issues` |
| Обход через прокси | свой профиль, пример ниже | как обычно |

### Обход через прокси

Адрес прокси у каждого свой, поэтому это не встроенный профиль, а пример своего `.spider/profiles/proxy.toml`. Пароль в файл не пишется: `{password}` подставляется из системного хранилища ключей — один раз `spider auth login --provider proxy`.

```toml
description = "Обход через прокси: запросы чередуются между адресами"
extends = "default"

[crawl]
proxy_urls = ["http://user:{password}@proxy1.example:8000", "http://user:{password}@proxy2.example:8000"]
concurrency = 10
```

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
