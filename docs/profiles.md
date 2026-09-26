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
| `crawl.max_depth` | `int \| None` | — | Не идти глубже стольких кликов от стартового URL; не задано — без ограничения. |
| `crawl.max_links_per_page` | `int \| None` | `10000` | Брать с одной страницы не больше стольких ссылок; не задано — все. |
| `crawl.max_url_length` | `int` | `2000` | Не обходить URL длиннее стольких символов. |
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
| `collect.images_srcset` | `bool` | `false` | Брать картинки и из атрибута srcset, а не только src. |
| `collect.css.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.css.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.js.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.js.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.media.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.media.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
| `collect.iframes.follow` | `bool` | `true` | Переходить по таким ссылкам (обходить или проверять цель). |
| `collect.iframes.store` | `bool` | `true` | Хранить сами ссылки в базе (для `spider links` и проверок ссылок). |
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
<!-- keys:end -->

## Рецепты

Появятся вместе с настройками, на которые они опираются (#20).
