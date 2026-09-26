# rb-spider — перечень функций и проверок

Чек-лист всего, что умеет Screaming Frog SEO Spider (SF, версия 24.3), с решением, **когда** (и нужно ли вообще) это делать в rb-spider. Плюс наши функции, которых в SF нет.

- Архитектура и принятые решения — [spec.md](spec.md).
- Полный исходный перечень SF (все проверки с определениями, вкладки, настройки, режимы, экспорты) — [reference/screaming-frog.md](reference/screaming-frog.md).

## Легенда

**Волна** — когда делаем:

| Метка | Значение |
|---|---|
| `MVP` | Первая рабочая версия: ядро обхода + базовые SEO-проверки |
| `v2` | Вторая волна: расширенный аудит (hreflang, JS, микроразметка, sitemap, сравнение обходов…) |
| `v3` | Внешние API и тяжёлая аналитика (Search Console, PageSpeed, Link Score, визуализации) |
| `backlog` | Возможно когда-нибудь; сейчас не планируем |
| `skip` | Не делаем (не нужно в CLI или закрывается другими средствами) |

**Статус:** `[ ]` — не сделано, `[x]` — сделано.

**Тип и приоритет SF** в скобках — как SF классифицирует проверку: **Issue** — ошибка, надо исправить; **Warning** — стоит проверить; **Opportunity** — возможность улучшить. Приоритет — High / Medium / Low. Мы наследуем эту классификацию как стартовую (spec.md, таблица `issues`).

**(не подтверждено)** — пункт в исходнике помечен как не найденный в документации SF (виден только на скриншоте или выведен косвенно).

**Ключи профиля** (`collect.images.follow` и т.п.) — там, где соответствие очевидно. Ключи из spec.md зафиксированы; остальные — предложение, окончательно закрепляются в `docs/profiles.md`.

Термины для новичка: **indexable** — страница, которую поисковик может проиндексировать (200, нет noindex, canonical на себя); **inlinks / outlinks** — входящие / исходящие ссылки страницы; **raw HTML** — ответ сервера как есть, **rendered HTML** — DOM после выполнения JavaScript в браузере.

## Сводка

| Раздел | `MVP` | `v2` | `v3` | `backlog` | `skip` | Всего |
|---|---:|---:|---:|---:|---:|---:|
| A. Проверки (issues) | 78 | 93 | 32 | 113 | 4 | 320 |
| B. Сбор данных и вкладки | 15 | 22 | 7 | 8 | 1 | 53 |
| C. Настройки обхода | 44 | 44 | 2 | 10 | 5 | 105 |
| D. Режимы | 6 | 3 | 2 | 4 | 1 | 16 |
| E. Экспорт и отчёты | 11 | 24 | 8 | 11 | 2 | 56 |
| F. Интеграции | 1 | 0 | 5 | 1 | 4 | 11 |
| G. Наше, чего нет в SF | 22 | 4 | 0 | 0 | 0 | 26 |
| **Итого** | **177** | **190** | **56** | **147** | **17** | **587** |

В разделе A 320 проверок SF, из них 92 — Accessibility (все `backlog`).

---

## A. Проверки (issues)

### Response Codes — коды ответа

- [x] `MVP` **Internal No Response** — внутренний URL не ответил вовсе (таймаут, отказ соединения, кривой URL) _(SF: Issue, High)_
- [x] `MVP` **Internal Client Error (4XX)** — внутренний URL отдаёт 4xx (например, 404) _(SF: Issue, High)_
- [x] `MVP` **Internal Server Error (5XX)** — внутренний URL отдаёт 5xx (500, 503…) _(SF: Issue, High)_
- [x] `MVP` **Internal Redirect Loop** — цепочка редиректов возвращается на уже пройденный URL (петля) _(SF: Issue, High)_
- [x] `MVP` **Internal Blocked by Robots.txt** — внутренний URL запрещён в robots.txt, поисковик не сможет его обойти _(SF: Warning, High)_
- [x] `MVP` **Internal Blocked Resource** — внутренний ресурс (картинка, JS, CSS) недоступен: запрещён robots.txt или отдаёт ошибку _(SF: Warning, High)_
- [x] `MVP` **Internal Redirect Chain** — редирект ведёт на URL, который снова редиректит (2+ «прыжка») _(SF: Warning, Medium)_
- [x] `MVP` **External Blocked Resource** — внешний ресурс (картинка, JS, CSS) запрещён robots.txt или отдаёт ошибку _(SF: Warning, Medium)_
- [x] `MVP` **Internal Redirection (3XX)** — внутренний URL отдаёт серверный редирект (301, 302…) _(SF: Warning, Low)_
- [x] `MVP` **Internal Redirection (Meta Refresh)** — редирект через `<meta http-equiv="refresh">` на стороне браузера _(SF: Warning, Low)_
- [x] `MVP` **Internal Redirection (HTTP Refresh)** — редирект через HTTP-заголовок `Refresh` _(SF: Warning, Low)_
- [ ] `v2` **Internal Redirection (JavaScript)** — редирект, выполняемый JavaScript (нужен рендеринг и сравнение URL до/после) _(SF: Warning, Low)_
- [x] `MVP` **External No Response** — внешняя ссылка не ответила _(SF: Warning, Low)_
- [x] `MVP` **External Client Error (4XX)** — внешняя ссылка отдаёт 4xx (битая) _(SF: Warning, Low)_
- [x] `MVP` **External Server Error (5XX)** — внешняя ссылка отдаёт 5xx _(SF: Warning, Low)_

### Security — безопасность

- [ ] `v2` **HTTP URLs** — на сайте встречаются URL по незащищённому HTTP _(SF: Issue, High)_
- [ ] `v2` **Mixed Content** — HTTPS-страница грузит ресурсы (картинки, JS, CSS) по HTTP _(SF: Issue, High)_
- [ ] `v2` **Form URL Insecure** — у формы `action` ведёт на HTTP-адрес _(SF: Issue, High)_
- [ ] `v2` **Form On HTTP URL** — форма расположена на HTTP-странице, введённые данные не защищены _(SF: Issue, High)_
- [ ] `v2` **Missing HSTS Header** — нет заголовка `Strict-Transport-Security` (браузер не обязан ходить только по HTTPS) _(SF: Warning, Low)_
- [ ] `v2` **Unsafe Cross Origin Links** — внешние ссылки с `target="_blank"` без `rel="noopener"`/`noreferrer` _(SF: Warning, Low)_
- [ ] `v2` **Protocol-Relative Resource Links** — ресурсы подключены протокол-относительными ссылками `//example.com/…` _(SF: Warning, Low)_
- [ ] `v2` **Missing Content-Security-Policy Header** — нет заголовка CSP, ограничивающего источники ресурсов _(SF: Warning, Low)_
- [ ] `v2` **Missing X-Content-Type-Options Header** — нет `X-Content-Type-Options: nosniff` _(SF: Warning, Low)_
- [ ] `v2` **Missing X-Frames-Options Header** — нет `X-Frame-Options: DENY|SAMEORIGIN` (защита от встраивания во фрейм) _(SF: Warning, Low)_
- [ ] `v2` **Missing Secure Referrer-Policy Header** — `Referrer-Policy` отсутствует или небезопасен _(SF: Warning, Low)_
- [ ] `v2` **Bad Content Type** — реальный тип содержимого не совпадает с заголовком `Content-Type` _(SF: Warning, Low)_

### URL — адреса

- [ ] `v2` **Multiple Slashes** — в пути несколько слешей подряд (`/page1//`) _(SF: Issue, Low)_
- [ ] `v2` **Contains A Space** — в URL есть пробел _(SF: Issue, Low)_
- [ ] `v2` **Broken Bookmark** — ссылка на якорь `#id`, которого нет на целевой странице _(SF: Issue, Low)_
- [ ] `v2` **Non ASCII Characters** — в URL символы вне ASCII (кириллица и т.п. без кодирования) _(SF: Warning, Low)_
- [ ] `v2` **Uppercase** — в URL заглавные буквы (риск дублей: URL чувствительны к регистру) _(SF: Warning, Low)_
- [ ] `v2` **Repetitive Path** — повторяющиеся сегменты пути (`/example/example/`) _(SF: Warning, Low)_
- [ ] `v2` **Internal Search** — URL похож на страницу внутреннего поиска сайта _(SF: Warning, Low)_
- [ ] `v2` **Parameters** — URL содержит GET-параметры (`?`, `&`) _(SF: Warning, Low)_
- [ ] `v2` **GA Tracking Parameters** — в URL метки Google Analytics (`utm_*` и т.п.) _(SF: Warning, Low)_
- [ ] `v2` **Underscores** — подчёркивания в URL (поисковики не всегда считают их разделителем слов) _(SF: Opportunity, Low)_
- [ ] `v2` **Over 115 Characters** — URL длиннее 115 символов _(SF: Opportunity, Low)_

### Page Titles — title

- [x] `MVP` **Missing** — нет `<title>`, он пустой или из пробелов _(SF: Issue, High)_
- [x] `MVP` **Multiple** — на странице несколько `<title>` _(SF: Issue, High)_
- [x] `MVP` **Outside \<head\>** — `<title>` стоит вне `<head>` _(SF: Issue, High)_
- [x] `MVP` **Duplicate** — одинаковый title у нескольких страниц _(SF: Opportunity, Medium)_
- [x] `MVP` **Over 60 Characters** — title длиннее 60 символов (может обрезаться в выдаче) _(SF: Opportunity, Medium)_
- [x] `MVP` **Below 30 Characters** — title короче 30 символов _(SF: Opportunity, Medium)_
- [ ] `v2` **Over 561 Pixels** — ширина title больше лимита выдачи Google в пикселях (нужна таблица ширин шрифта) _(SF: Opportunity, Medium)_
- [ ] `v2` **Below 200 Pixels** — title заметно уже лимита выдачи в пикселях _(SF: Opportunity, Medium)_
- [x] `MVP` **Same as H1** — title дословно совпадает с `<h1>` _(SF: Opportunity, Low)_

### Meta Description

- [x] `MVP` **Multiple** — несколько meta description на странице _(SF: Issue, Medium)_
- [x] `MVP` **Outside \<head\>** — meta description вне `<head>` (поисковик может проигнорировать) _(SF: Issue, Medium)_
- [x] `MVP` **Missing** — meta description нет, пустой или из пробелов _(SF: Opportunity, Low)_
- [x] `MVP` **Duplicate** — одинаковый meta description у нескольких страниц _(SF: Opportunity, Low)_
- [x] `MVP` **Over 155 Characters** — длиннее 155 символов (обрежется в сниппете) _(SF: Opportunity, Low)_
- [x] `MVP` **Below 70 Characters** — короче 70 символов _(SF: Opportunity, Low)_
- [ ] `v2` **Over 985 Pixels** — шире лимита сниппета в пикселях _(SF: Opportunity, Low)_
- [ ] `v2` **Below 400 Pixels** — заметно уже лимита сниппета в пикселях _(SF: Opportunity, Low)_

### H1

- [x] `MVP` **Missing** — нет `<h1>`, пустой или из пробелов _(SF: Issue, Medium)_
- [x] `MVP` **Multiple** — несколько `<h1>` на странице _(SF: Warning, Medium)_
- [x] `MVP` **Alt Text in h1** — текст h1 взят из alt картинки внутри `<h1>` _(SF: Warning, Low)_
- [x] `MVP` **Non-sequential** — `<h1>` не первый заголовок на странице _(SF: Warning, Low)_
- [x] `MVP` **Duplicate** — одинаковый h1 у нескольких страниц _(SF: Opportunity, Low)_
- [x] `MVP` **Over 70 Characters** — h1 длиннее 70 символов _(SF: Opportunity, Low)_

### H2

- [x] `MVP` **Missing** — нет `<h2>`, пустой или из пробелов _(SF: Warning, Low)_
- [x] `MVP` **Multiple** — несколько `<h2>` (информационно) _(SF: Warning, Low)_
- [x] `MVP` **Non-sequential** — `<h2>` идёт не сразу вторым уровнем после `<h1>` _(SF: Warning, Low)_
- [x] `MVP` **Duplicate** — одинаковые h2 у разных страниц _(SF: Opportunity, Low)_
- [x] `MVP` **Over 70 Characters** — h2 длиннее 70 символов _(SF: Opportunity, Low)_

### Content — контент

- [x] `MVP` **Exact Duplicates** — страницы полностью идентичны (совпадает md5-хэш) _(SF: Issue, High)_
- [ ] `backlog` **Spelling Errors** — орфографические ошибки в тексте _(SF: Issue, Medium)_
- [ ] `backlog` **Grammar Errors** — грамматические ошибки в тексте _(SF: Issue, Medium)_
- [ ] `v2` **Soft 404 Pages** — страница отдаёт 200, но по содержимому — «страница не найдена» (эвристика) _(SF: Warning, High)_
- [x] `MVP` **Lorem Ipsum Placeholder** — на странице остался текст-заглушка «Lorem ipsum» _(SF: Warning, High)_
- [ ] `v2` **Near Duplicates** — почти-дубли по тексту, сходство ≥ порога (90 %), MinHash _(SF: Warning, Medium)_
- [ ] `backlog` **Semantically Similar** — страницы близки по смыслу (косинусная близость эмбеддингов) _(SF: Warning, Medium)_
- [ ] `backlog` **Low Relevance Content** — страница выбивается из общей тематики сайта (эмбеддинги) _(SF: Warning, Low)_
- [x] `MVP` **Low Content Pages** — мало текста: меньше 200 слов (порог настраивается) _(SF: Opportunity, Medium)_
- [ ] `v2` **Readability Difficult** — текст трудно читать по формуле Flesch _(SF: Opportunity, Low)_
- [ ] `v2` **Readability Very Difficult** — текст очень трудно читать по формуле Flesch _(SF: Opportunity, Low)_

### Images — изображения

- [x] `MVP` **Missing Alt Text** — атрибут alt есть, но пустой _(SF: Issue, Low)_
- [x] `MVP` **Missing Alt Attribute** — атрибута alt нет вовсе _(SF: Issue, Low)_
- [ ] `v2` **Background Images** — картинки из CSS `background` и подгружаемые динамически (нужен рендеринг) _(SF: Warning, Low)_
- [x] `MVP` **Over 100 kb** — картинка тяжелее 100 КБ _(SF: Opportunity, Medium)_
- [x] `MVP` **Alt Text Over 100 Characters** — alt длиннее 100 символов _(SF: Opportunity, Low)_
- [ ] `v2` **Incorrectly Sized Images** — реальный размер картинки не совпадает с отображаемым (нужен рендеринг) _(SF: Opportunity, Low)_
- [x] `MVP` **Missing Size Attributes** — у `<img>` не заданы `width`/`height` в HTML _(SF: Opportunity, Low)_

### Canonicals

- [x] `MVP` **Multiple Conflicting** — несколько canonical с разными URL (в HTML, в HTTP-заголовке или в обоих) _(SF: Issue, High)_
- [x] `MVP` **Non-Indexable Canonical** — canonical указывает на неиндексируемый URL _(SF: Issue, High)_
- [x] `MVP` **Invalid Attribute In Annotation** — у `rel="canonical"` лишние атрибуты `hreflang`, `lang`, `media` или `type` _(SF: Issue, High)_
- [x] `MVP` **Contains Fragment URL** — canonical содержит фрагмент `#…` _(SF: Issue, High)_
- [x] `MVP` **Outside \<head\>** — `<link rel="canonical">` вне `<head>` _(SF: Issue, High)_
- [x] `MVP` **Canonicalised** — canonical указывает на другой URL (страница «склеена» с другой) _(SF: Warning, High)_
- [x] `MVP` **Missing** — canonical нет ни в HTML, ни в HTTP-заголовке _(SF: Warning, Medium)_
- [x] `MVP` **Unlinked** — URL найден только через canonical, обычными ссылками на него не ведут _(SF: Warning, Medium)_
- [x] `MVP` **Multiple** — несколько canonical (пусть и одинаковых) _(SF: Warning, Low)_
- [x] `MVP` **Canonical Is Relative** — canonical задан относительным, а не абсолютным URL _(SF: Warning, Low)_

### Pagination — пагинация (rel next/prev)

- [ ] `v2` **Pagination URL Not In Anchor Tag** — URL из `rel="next"`/`"prev"` не встречается обычной ссылкой `<a>` на странице _(SF: Issue, High)_
- [ ] `v2` **Non-200 Pagination URLs** — URL из next/prev отвечает не 200 _(SF: Issue, High)_
- [ ] `v2` **Unlinked Pagination URLs** — на URL из next/prev нет ссылок по сайту _(SF: Issue, Medium)_
- [ ] `v2` **Multiple Pagination URLs** — несколько `rel="next"` или `rel="prev"` на странице _(SF: Issue, Low)_
- [ ] `v2` **Pagination Loop** — next/prev зацикливаются на уже пройденный URL _(SF: Issue, Low)_
- [ ] `v2` **Sequence Error** — ошибка в последовательности next/prev (цепочка не сходится) _(SF: Issue, Low)_
- [ ] `v2` **Non-Indexable** — страница пагинации неиндексируемая _(SF: Warning, High)_

### Directives — директивы (meta robots, X-Robots-Tag)

- [x] `MVP` **Outside \<head\>** — meta robots вне `<head>` _(SF: Issue, High)_
- [x] `MVP` **NoImageIndex** — директива `noimageindex` (не индексировать картинки страницы) _(SF: Issue, Low)_
- [x] `MVP` **Noindex** — `noindex` в meta robots или X-Robots-Tag: страница не попадёт в индекс _(SF: Warning, High)_
- [x] `MVP` **Nofollow** — `nofollow`: поисковику не переходить по ссылкам страницы _(SF: Warning, High)_
- [x] `MVP` **None** — `none` = `noindex, nofollow` _(SF: Warning, High)_
- [x] `MVP` **Unavailable_After** — `unavailable_after`: убрать из индекса после даты _(SF: Warning, Medium)_
- [x] `MVP` **NoSnippet** — `nosnippet`: не показывать сниппет в выдаче _(SF: Warning, Low)_
- [x] `MVP` **NoODP** — устаревшая директива `noodp` _(SF: Warning, Low)_
- [x] `MVP` **NoYDIR** — устаревшая директива `noydir` _(SF: Warning, Low)_
- [x] `MVP` **NoTranslate** — `notranslate`: не предлагать перевод страницы _(SF: Warning, Low)_

### Hreflang

- [ ] `v2` **Non-200 Hreflang URLs** — URL из hreflang отвечает не 200 (редирект, 4xx, закрыт robots…) _(SF: Issue, High)_
- [ ] `v2` **Missing Return Links** — альтернативная страница не ссылается hreflang-ом обратно _(SF: Issue, High)_
- [ ] `v2` **Inconsistent Language & Region Confirmation Links** — обратная ссылка указывает другой язык/регион, чем сама страница _(SF: Issue, High)_
- [ ] `v2` **Non-Canonical Return Links** — обратные hreflang-ссылки ведут на неканонические URL _(SF: Issue, High)_
- [ ] `v2` **Noindex Returns Links** — обратные ссылки ведут на страницы с noindex _(SF: Issue, High)_
- [ ] `v2` **Incorrect Language & Region Codes** — неверный код языка (ISO 639-1) или региона (ISO 3166-1 Alpha 2) _(SF: Issue, High)_
- [ ] `v2` **Multiple Entries** — один и тот же язык/регион указан несколько раз _(SF: Issue, High)_
- [ ] `v2` **Not Using Canonical** — в собственной hreflang-разметке страница указана не своим canonical URL _(SF: Issue, High)_
- [ ] `v2` **Outside \<head\>** — hreflang-элемент вне `<head>` _(SF: Issue, High)_
- [ ] `v2` **Unlinked Hreflang URLs** — URL найден только через hreflang, обычных ссылок нет _(SF: Issue, Medium)_
- [ ] `v2` **Missing Self Reference** — нет hreflang-ссылки страницы на саму себя _(SF: Warning, Low)_
- [ ] `v2` **Missing X-Default** — нет `x-default` (необязательно) _(SF: Warning, Low)_

### JavaScript — сравнение raw и rendered HTML

- [ ] `v2` **Noindex Only in Original HTML** — noindex есть в исходном HTML, но исчезает после JS _(SF: Issue, High)_
- [ ] `v2` **Nofollow Only in Original HTML** — nofollow есть в исходном HTML, но исчезает после JS _(SF: Issue, High)_
- [ ] `v2` **Canonical Mismatch** — canonical в исходном и отрендеренном HTML разный _(SF: Issue, High)_
- [ ] `v2` **Uses Old AJAX Crawling Scheme URLs** — URL со старой схемой AJAX `#!` (отменена в 2015) _(SF: Issue, Medium)_
- [ ] `v2` **Uses Old AJAX Crawling Scheme Meta Fragment Tag** — на странице `<meta name="fragment">` старой AJAX-схемы _(SF: Issue, Medium)_
- [ ] `v2` **Pages with Blocked Resources** — ресурсы страницы (JS, CSS, картинки) заблокированы при рендеринге _(SF: Warning, High)_
- [ ] `v2` **Contains JavaScript Links** — ссылки, которые появляются только после выполнения JS _(SF: Warning, Medium)_
- [ ] `v2` **Contains JavaScript Content** — текст, который появляется только после выполнения JS _(SF: Warning, Medium)_
- [ ] `v2` **Page Title Only in Rendered HTML** — title есть только после JS _(SF: Warning, Medium)_
- [ ] `v2` **Page Title Updated by JavaScript** — JS меняет title _(SF: Warning, Medium)_
- [ ] `v2` **Meta Description Only in Rendered HTML** — meta description есть только после JS _(SF: Warning, Medium)_
- [ ] `v2` **Meta Description Updated by JavaScript** — JS меняет meta description _(SF: Warning, Medium)_
- [ ] `v2` **H1 Only in Rendered HTML** — h1 есть только после JS _(SF: Warning, Medium)_
- [ ] `v2` **H1 Updated by JavaScript** — JS меняет h1 _(SF: Warning, Medium)_
- [ ] `v2` **Canonical Only in Rendered HTML** — canonical есть только после JS _(SF: Warning, Low)_
- [ ] `v2` **Pages With JavaScript Errors** — ошибки JS в консоли браузера при рендеринге _(SF: Warning, Low)_

### Links — ссылки

- [x] `MVP` **Outlinks To Localhost** — ссылки на `localhost` / `127.0.0.1` _(SF: Issue, High)_
- [x] `MVP` **Pages With Uncrawlable Internal Outlinks** — внутренние «ссылки» не в `<a href>` (onclick, `<span href>`, `javascript:`) _(SF: Warning, High)_
- [x] `MVP` **Pages Without Internal Outlinks** — на странице нет ни одной внутренней ссылки (тупик) _(SF: Warning, High)_
- [x] `MVP` **Non-Indexable Page Inlinks Only** — на индексируемую страницу ссылаются только неиндексируемые _(SF: Warning, High)_
- [x] `MVP` **Internal Nofollow Outlinks** — внутренние ссылки с `rel="nofollow"` _(SF: Warning, Low)_
- [x] `MVP` **Pages With High External Outlinks** — внешних follow-ссылок больше порога _(SF: Warning, Low)_
- [x] `MVP` **Pages With High Internal Outlinks** — внутренних follow-ссылок больше порога (по умолчанию 1000) _(SF: Warning, Low)_
- [x] `MVP` **Follow & Nofollow Internal Inlinks To Page** — на страницу ведут и follow-, и nofollow-ссылки _(SF: Warning, Low)_
- [x] `MVP` **Internal Nofollow Inlinks Only** — на страницу ведут только nofollow-ссылки _(SF: Warning, Low)_
- [x] `MVP` **Pages With High Crawl Depth** — глубина от стартовой страницы ≥ 4 кликов (порог настраивается) _(SF: Opportunity, Medium)_
- [x] `MVP` **Internal Outlinks With No Anchor Text** — внутренние ссылки без анкора (или картинка-ссылка без alt) _(SF: Opportunity, Low)_
- [x] `MVP` **Non-Descriptive Anchor Text In Internal Outlinks** — неинформативный анкор («подробнее», «click here»; список настраивается) _(SF: Opportunity, Low)_

### AMP

Все проверки AMP — `backlog`: технология теряет актуальность, отдельный валидатор.

- [ ] `backlog` **Non-200 Response** — AMP-URL отвечает не 200 _(SF: Issue, High)_
- [ ] `backlog` **Missing Non-AMP Return Link** — обычная версия не ссылается `rel="amphtml"` обратно на AMP _(SF: Issue, High)_
- [ ] `backlog` **Missing Canonical to Non-AMP** — canonical AMP-страницы ведёт на другую AMP, а не на обычную версию _(SF: Issue, High)_
- [ ] `backlog` **Non-Indexable Canonical** — canonical AMP-страницы неиндексируемый _(SF: Issue, High)_
- [ ] `backlog` **Missing \<html amp\> Tag** — нет `<html amp>` / `<html ⚡>` _(SF: Issue, High)_
- [ ] `backlog` **Missing/Invalid Doctype HTML Tag** — нет или неверный `<!doctype html>` _(SF: Issue, High)_
- [ ] `backlog` **Missing Head Tag** — нет `<head>` (в AMP обязателен) _(SF: Issue, High)_
- [ ] `backlog` **Missing Body Tag** — нет `<body>` (в AMP обязателен) _(SF: Issue, High)_
- [ ] `backlog` **Missing Canonical** — у AMP-страницы нет canonical _(SF: Issue, High)_
- [ ] `backlog` **Missing/Invalid Meta Charset Tag** — нет `<meta charset="UTF-8">` первым в head _(SF: Issue, High)_
- [ ] `backlog` **Missing/Invalid Meta Viewport Tag** — нет или неверный meta viewport _(SF: Issue, High)_
- [ ] `backlog` **Missing/Invalid AMP Script** — нет или неверный скрипт AMP runtime _(SF: Issue, High)_
- [ ] `backlog` **Missing/Invalid AMP Boilerplate** — нет обязательного AMP boilerplate в head _(SF: Issue, High)_
- [ ] `backlog` **Contains Disallowed HTML** — HTML, запрещённый валидатором AMP _(SF: Issue, High)_
- [ ] `backlog` **Other Validation Errors** — прочие ошибки валидатора AMP _(SF: Issue, High)_
- [ ] `backlog` **Indexable** — AMP-страница индексируемая, хотя должна склеиваться canonical-ом с обычной _(SF: Warning, High)_

### Structured Data — микроразметка (extruct)

- [ ] `v2` **Validation Errors** — ошибки валидации по словарю Schema.org _(SF: Issue, High)_
- [ ] `v2` **Rich Result Validation Errors** — ошибки для расширенных результатов Google (нет обязательных свойств) _(SF: Issue, High)_
- [ ] `v2` **Parse Errors** — микроразметка не разбирается (битый JSON-LD и т.п.) _(SF: Issue, High)_
- [ ] `v2` **Missing** — на странице нет микроразметки _(SF: Opportunity, Low)_
- [ ] `v2` **Validation Warnings** — предупреждения валидации (например, устаревший data-vocabulary.org) _(SF: Opportunity, Low)_
- [ ] `v2` **Rich Result Validation Warnings** — нет рекомендуемых свойств для расширенных результатов _(SF: Opportunity, Low)_

### Sitemaps — анализ XML sitemap (через rb-sitemap-xml)

- [ ] `v2` **XML Sitemap With Over 50k URLs** — в одном sitemap больше 50 000 URL _(SF: Issue, High)_
- [ ] `v2` **XML Sitemap Over 50mb** — файл sitemap больше 50 МБ _(SF: Issue, High)_
- [ ] `v2` **URLs Not In Sitemap** — URL найден обходом, но его нет в sitemap _(SF: Issue, Medium)_
- [ ] `v2` **Orphan URLs** — URL есть в sitemap, но обходом по ссылкам не найден («сирота») _(SF: Issue, Medium)_
- [ ] `v2` **Non-Indexable URLs In Sitemap** — в sitemap неиндексируемые URL _(SF: Issue, Medium)_
- [ ] `v2` **URLs In Multiple Sitemaps** — URL указан в нескольких sitemap _(SF: Warning, Low)_

### PageSpeed — скорость (PageSpeed Insights / Lighthouse)

- [ ] `v3` **Document Request Latency** — задержка основного документа: редиректы, медленный ответ, нет сжатия _(SF: Opportunity, Medium)_
- [ ] `v3` **LCP Request Discovery** — ресурс LCP (крупнейший элемент экрана) обнаруживается поздно _(SF: Opportunity, Medium)_
- [ ] `v3` **Render Blocking Requests** — скрипты/стили блокируют первую отрисовку _(SF: Opportunity, Medium)_
- [ ] `v3` **Network Dependency Tree** — длинные цепочки загрузки на критическом пути _(SF: Opportunity, Medium)_
- [ ] `v3` **Use Efficient Cache Lifetimes** — ресурсы без нормального HTTP-кэширования _(SF: Opportunity, Medium)_
- [ ] `v3` **Layout Shift Culprits** — элементы сдвигают вёрстку при загрузке (CLS) _(SF: Opportunity, Medium)_
- [ ] `v3` **Improve Image Delivery** — картинки можно отдавать легче (формат, размер, сжатие) _(SF: Opportunity, Medium)_
- [ ] `v3` **Forced Reflow** — принудительный пересчёт раскладки тормозит отрисовку _(SF: Opportunity, Medium)_
- [ ] `v3` **Legacy JavaScript** — лишние полифиллы для старых браузеров _(SF: Opportunity, Medium)_
- [ ] `v3` **Duplicated JavaScript** — одна и та же JS-библиотека в нескольких бандлах _(SF: Opportunity, Medium)_
- [ ] `v3` **Avoid Enormous Network Payloads** — слишком большой общий вес страницы _(SF: Opportunity, Medium)_
- [ ] `v3` **Minify CSS** — CSS не минифицирован _(SF: Opportunity, Medium)_
- [ ] `v3` **Minify JavaScript** — JS не минифицирован _(SF: Opportunity, Medium)_
- [ ] `v3` **Reduce Unused CSS** — много неиспользуемого CSS _(SF: Opportunity, Medium)_
- [ ] `v3` **Reduce Unused JavaScript** — много неиспользуемого JS _(SF: Opportunity, Medium)_
- [ ] `v3` **Reduce JavaScript Execution Time** — выполнение JS дольше 2 секунд _(SF: Opportunity, Medium)_
- [ ] `v3` **Minimize Main-Thread Work** — перегружен главный поток браузера _(SF: Opportunity, Medium)_
- [ ] `v3` **Optimize DOM Size** — слишком большой DOM, пересчёт стилей > 40 мс _(SF: Opportunity, Low)_
- [ ] `v3` **Font Display** — шрифты «мигают» или невидимы при загрузке _(SF: Opportunity, Low)_

### Mobile — мобильная версия

Проверки через Lighthouse (PSI) — `v3`. Три пункта определяются по самому HTML без Lighthouse, поэтому вынесены в `v2`.

- [ ] `v2` **Viewport Not Set** — нет `<meta name="viewport">` или в нём нет `width=` _(SF: Issue, High)_
- [ ] `v3` **Content Not Sized Correctly** — контент шире или уже экрана телефона _(SF: Issue, High)_
- [ ] `v3` **Illegible Font Size** — слишком мелкий шрифт для мобильных _(SF: Issue, High)_
- [ ] `v2` **Contains Unsupported Plugins** — Flash, Silverlight, Java-апплеты (`<object>`, `<embed>`) _(SF: Issue, High)_
- [ ] `v3` **Target Size** — слишком маленькие или тесные элементы для нажатия пальцем _(SF: Issue, Medium)_
- [ ] `v2` **Mobile Alternate Link** — есть `rel="alternate" media=…` на отдельную мобильную версию _(SF: Warning, High)_

### Accessibility — доступность (axe-core)

Все 92 проверки — `backlog` (движок axe-core в браузере; определения — в [справочнике](reference/screaming-frog.md#accessibility-92)).

<details>
<summary>Список проверок Accessibility (92)</summary>

- [ ] `backlog` **Best Practice – Accesskey Attribute Value Must Be Unique** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – Elements Must Not Have Tabindex Greater Than Zero** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – ARIA Dialog & Alertdialog Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – ARIA Treeitem Nodes Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – Role=text Should Have No Focusable Descendants** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – Form Elements Should Have Visible Label** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – Frames Should Be Tested With axe-core** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – Scope Attribute Should Be Used Correctly On Tables** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Scrollable Region Requires Keyboard Access** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Required ARIA Attributes Must Be Provided** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Attribute Must Be Used As Specified For Role** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Attributes Require Valid Values** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Attributes Require Valid Names** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Commands Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Input Fields Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Meter Nodes Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Progressbar Nodes Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Roles Must Be Contained By Required Parent** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Roles Require Valid Values** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Toggle Fields Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – ARIA Tooltip Nodes Require Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Certain ARIA Roles Must Contain Specific Children** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Aria-braille Require Non-braille Equivalent** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Aria-hidden Elements Contains Focusable Elements** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Aria-hidden=true Must Not Be Used In <body>** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Elements Must Only Use Permitted ARIA Attributes** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Elements Must Use Allowed ARIA Attributes** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – IDs Used In ARIA & Labels Must Be Unique** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Page Requires Means To Bypass Repeated Blocks** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Form <input> Elements Require Labels** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Frames Require Title Attribute** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Frames Require Unique Title Attribute** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Frames With Focusable Content Must Not Use tabindex=-1** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Page Must Contain <title>** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – HTML Element Lang Attribute Value Must Be Valid** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – HTML Element Requires Lang Attribute** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Image Button Requires Alternate Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Images Require Alternate Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – <object> Elements Require Alternate Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Active <area> Elements Require Alternate Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Elements Marked role=img Require Alternate Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – SVG Images & Graphics Require Accessible Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – <video> Elements Require <track> For Captions** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – <video> or <audio> Elements Must Not Auto-play** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Buttons Require Discernible Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Input Buttons Require Discernible Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Links Require Discernible Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Links Must Be Distinguishable** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Select Element Requires Accessible Name** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Summary Elements Require Discernible Text** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Deprecated <marquee> Element Must Not Be Used** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Interactive Controls Must Not Be Nested** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – List Items Must Be Contained In List Elements** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Lists Must Only Contain <li> Content Elements** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – <dt> & <dd> Elements Must Be Contained by <dl>** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – <dl> Must Only Have Ordered <dt> & <dd> Groups** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – <blink> Elements Deprecated & Must Not Be Used** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – <th> Element Requires Associated Data Cells** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 A – Table Header Attr Must Refer To Cell In Same Table** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 AA – Meta Viewport Zoom & Scaling Disabled** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 AA – Lang Attribute Requires Valid Value** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 AA – Text Requires Higher Color Contrast to Background** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.0 AAA – Text Requires Higher Color Contrast Ratio** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.1 AA – Autocomplete Attribute Must Be Used Correctly** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.1 AA – Inline Text Spacing Must Be Adjustable** _(SF: Warning, High)_
- [ ] `backlog` **WCAG 2.2 AA – Touch Targets Require Sufficient Size & Spacing** _(SF: Warning, High)_
- [ ] `backlog` **Best Practice – Skip-link Target Should Exist & Be Focusable** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – All Page Content Must Be Contained By Landmarks** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Page Requires One Main Landmark** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Page Must Not Have More Than One Banner Landmark** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Banner Landmark Must Not Be In Another Landmark** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Page Must Not Have Multiple Contentinfo Landmarks** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Page Requires At Most One Main Landmark** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Complementary Landmarks & Asides Must Be Top Level** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Contentinfo Landmark Must Be Top Level Landmark** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Main Landmark Must Not Be In Another Landmark** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Landmarks Require Unique Role Or Accessible Name** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Page Must Contain <h1>** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Heading Levels Should Only Increase By One** _(SF: Warning, Medium)_
- [ ] `backlog` **WCAG 2.0 A – Form Field Must Not Have Multiple Label Elements** _(SF: Warning, Medium)_
- [ ] `backlog` **WCAG 2.0 A – HTML Lang & XML Lang Value Should Match** _(SF: Warning, Medium)_
- [ ] `backlog` **Best Practice – Ensure Elements Marked Presentational Are Ignored** _(SF: Warning, Low)_
- [ ] `backlog` **Best Practice – ARIA Role Should Be Appropriate For Element** _(SF: Warning, Low)_
- [ ] `backlog` **Best Practice – Headings Should Not Be Empty** _(SF: Warning, Low)_
- [ ] `backlog` **Best Practice – Meta Viewport Should Allow Zoom & Scale Up to 500%** _(SF: Warning, Low)_
- [ ] `backlog` **Best Practice – Alt Text Should Not Be Repeated As Text** _(SF: Warning, Low)_
- [ ] `backlog` **Best Practice – Table Headers Require Discernible Text** _(SF: Warning, Low)_
- [ ] `backlog` **Best Practice – Table With Identical Summary & Caption Text** _(SF: Warning, Low)_
- [ ] `backlog` **WCAG 2.0 A – Deprecated ARIA Roles Must Not Be Used** _(SF: Warning, Low)_
- [ ] `backlog` **WCAG 2.0 A – Server-Side Image Maps Must Not Be Used** _(SF: Warning, Low)_
- [ ] `backlog` **WCAG 2.0 AAA – Delayed Meta Refresh Must Not Be Used** _(SF: Warning, Low)_
- [ ] `backlog` **WCAG 2.0 AAA – Links With Same Accessible Name** _(SF: Warning, Low)_

</details>

### Analytics — Google Analytics

Интеграция с GA4 не делается (`skip`).

- [ ] `skip` **Orphan URLs** — URL есть в GA, но обходом не найден _(SF: Issue, Medium)_
- [ ] `skip` **Bounce Rate Above 70%** — показатель отказов выше 70 % _(SF: Warning, Low)_
- [ ] `skip` **No GA Data** — по URL нет данных в GA _(SF: Warning, Low)_
- [ ] `skip` **Non-Indexable with GA Data** — неиндексируемый URL, но с трафиком в GA _(SF: Warning, Low)_

### Search Console

- [ ] `v3` **Page is Not Mobile Friendly** — по данным GSC у страницы проблемы на мобильных _(SF: Issue, High)_
- [ ] `v3` **Orphan URLs** — URL есть в отчёте эффективности GSC, но обходом не найден _(SF: Issue, Medium)_
- [ ] `v3` **URL is on Google, But Has Issues** — в индексе, но есть проблемы (мобильность, AMP, rich results) _(SF: Issue, Medium)_
- [ ] `v3` **AMP URL is Invalid** — AMP-URL с ошибкой, мешающей индексации _(SF: Issue, Medium)_
- [ ] `v3` **Rich Result is Invalid** — ошибка расширенного результата, он не покажется в выдаче _(SF: Issue, Medium)_
- [ ] `v3` **Indexable URL Not Indexed** — индексируемый по нашим данным URL не в индексе Google _(SF: Warning, High)_
- [ ] `v3` **User-Declared Canonical Not Selected** — Google выбрал другой canonical, чем указан на странице _(SF: Warning, Medium)_
- [ ] `v3` **No Search Analytics Data** — у URL нет показов в GSC _(SF: Warning, Low)_
- [ ] `v3` **Non-Indexable with Search Analytics Data** — неиндексируемый URL, но с показами в GSC _(SF: Warning, Low)_
- [ ] `v3` **URL Is Not on Google** — URL не в индексе Google _(SF: Warning, Low)_

### Validation — валидность HTML

- [ ] `v2` **Missing \<head\> Tag** — в HTML нет `<head>` _(SF: Issue, High)_
- [ ] `v2` **Multiple \<head\> Tags** — несколько `<head>` _(SF: Issue, High)_
- [ ] `v2` **Missing \<body\> Tag** — нет `<body>` _(SF: Issue, High)_
- [ ] `v2` **Multiple \<body\> Tags** — несколько `<body>` _(SF: Issue, High)_
- [ ] `v2` **HTML Document Over 2MB** — HTML больше 2 МБ (Googlebot читает только первые 2 МБ) _(SF: Issue, High)_
- [ ] `v2` **Resource Over 2MB** — JS/CSS-файл больше 2 МБ _(SF: Issue, High)_
- [ ] `v2` **Invalid HTML Elements In \<head\>** — недопустимые элементы в `<head>`: Google считает head закончившимся и игнорирует остальное _(SF: Warning, High)_
- [ ] `v2` **\<body\> Element Preceding \<html\>** — элементы body (`<div>`, `<p>`…) стоят до `<html>` _(SF: Warning, High)_
- [ ] `v2` **\<head\> Not First In \<html\> Element** — `<head>` не первый элемент внутри `<html>` _(SF: Warning, High)_
- [ ] `backlog` **High Carbon Rating** — страница получает углеродный рейтинг F (Sustainable Web Design) _(SF: Opportunity, Low)_

---

## B. Сбор данных и вкладки

Информационные фильтры и данные, которые не являются проблемами (проблемы — в разделе A). Сгруппировано по вкладкам SF; в CLI это колонки `spider urls` / `spider url` / `spider links`.

### Основные вкладки и фильтры

- [ ] `MVP` **Internal / External: тип содержимого** — фильтры HTML, JavaScript, CSS, Images, PDF, Other, Unknown (Flash — `skip`)
- [ ] `MVP` **Response Codes: Success (2XX)** — список успешных URL; колонки Response Time, Redirect URL, Redirect Type
- [ ] `v2` **Security: HTTPS URLs** — список URL по HTTPS
- [ ] `v2` **Meta Keywords** — сбор meta keywords и фильтры Missing / Duplicate / Multiple
- [ ] `MVP` **Canonicals: Contains Canonical, Self Referencing** — есть canonical / canonical на себя; колонки HTML- и HTTP-canonical
- [ ] `v2` **Pagination: Contains Pagination, First Page, Paginated 2+ Pages** — сбор rel next/prev
- [ ] `MVP` **Directives: Index, Follow, NoArchive, Max-Snippet, Max-Image-Preview, Max-Video-Preview, Refresh** — все директивы meta robots и X-Robots-Tag
- [x] `MVP` **Indexability + Indexability Status** — индексируемость и причина (noindex, canonicalised, redirect, blocked…) у каждого URL
- [ ] `v2` **Hreflang: Contains Hreflang, Missing** — hreflang из HTML, HTTP-заголовка и sitemap
- [ ] `v2` **Structured Data: Contains, Missing, JSON-LD / Microdata / RDFa URLs** — типы и формат разметки
- [ ] `v2` **Sitemaps: URLs In Sitemap** — какие URL есть в sitemap
- [ ] `v2` **JavaScript: колонки raw vs rendered** — word count, title, description, h1, canonical, meta robots до и после JS
- [ ] `MVP` **Links: колонки** — crawl depth, inlinks / unique inlinks, outlinks / unique outlinks, external outlinks, % of total
- [ ] `v3` **Links: Link Score** — внутренний «PageRank» 0–100
- [ ] `v2` **Custom Search / Custom Extraction** — вкладки с результатами пользовательских поисков и извлечений
- [ ] `backlog` **Custom JavaScript** — результаты пользовательских JS-сниппетов
- [ ] `backlog` **AMP: Non-Indexable** — список неиндексируемых AMP
- [ ] `skip` **Analytics: Sessions Above 0** — URL с сессиями в GA
- [ ] `v3` **Search Console: Clicks Above 0** + колонки URL Inspection (Coverage, Last Crawl, Google-Selected Canonical…)
- [ ] `v3` **Link Metrics** — метрики Majestic / Ahrefs / Moz по URL, поддомену, домену
- [ ] `backlog` **AI** — ответы LLM по промптам на каждую страницу
- [ ] `v2` **Change Detection** — что изменилось между обходами: индексируемость, title, description, h1, word count, crawl depth, inlinks/outlinks, типы разметки, контент

### Извлекаемые данные страницы (Spider > Extraction)

- [ ] `MVP` **Page details** — title, meta description, h1, h2, word count, page size, hash (md5)
- [ ] `MVP` **URL details** — response time, заголовок Last-Modified, полные HTTP-заголовки запроса и ответа
- [ ] `v2` **Readability** — Flesch Reading Ease, среднее число слов в предложении
- [ ] `v2` **Text to Code Ratio** — доля текста в HTML
- [ ] `v2` **Forms** — формы на странице (для проверок Security)
- [ ] `v2` **Cookies** — cookies каждого URL
- [ ] `backlog` **PDF** — свойства PDF (автор, даты, страницы, слова), анкоры ссылок внутри PDF, сохранение PDF

### Нижние вкладки SF (детали выбранного URL) → `spider url` / `spider links`

- [ ] `MVP` **URL Details** — сводка по URL: код, тип, размер, глубина, число ссылок
- [x] `MVP` **Inlinks / Outlinks** — ссылки с колонками: анкор, alt, follow, target, rel, код ответа цели
- [ ] `v2` **Link Path, Link Position, Link Origin** — XPath ссылки, её зона (nav, header, footer, content…), откуда взята (raw / rendered HTML)
- [ ] `MVP` **Image Details** — картинки страницы: alt, размеры в атрибутах, вес
- [ ] `v2` **Image Details: real / display dimensions** — реальные и отображаемые размеры, потенциальная экономия (нужен рендеринг)
- [ ] `MVP` **Resources** — JS/CSS/картинки, подключённые на странице
- [ ] `v2` **SERP Snippet** — эмуляция сниппета Google с обрезкой по пикселям (без редактирования)
- [ ] `v3` **Rendered Page** — скриншот отрендеренной страницы
- [ ] `v3` **View Source** — просмотр исходного и отрендеренного HTML рядом
- [ ] `MVP` **HTTP Headers** — заголовки запроса и ответа
- [ ] `v2` **Duplicate Details** — пары дублей и почти-дублей с процентом сходства и diff
- [ ] `v2` **Structured Data Details** — дерево свойств разметки и ошибки валидации
- [ ] `v2` **Chrome Console Log** — ошибки и предупреждения JS при рендеринге
- [ ] `v3` **Lighthouse Details** — метрики PSI по URL
- [ ] `backlog` **Accessibility Details**, **Spelling & Grammar Details**
- [ ] `backlog` **N-grams** — частоты фраз из 1–6 слов (нужен сохранённый HTML)
- [ ] `v2` **Crawl Path** — кратчайший путь, которым краулер нашёл URL

### Правая панель SF → `spider status` / `spider issues`

- [ ] `MVP` **Overview** — сводка обхода: число URL по вкладкам и фильтрам
- [ ] `MVP` **Issues** — все сработавшие проверки: тип, приоритет, число URL, % от общего, описание
- [ ] `v2` **Site Structure** — дерево каталогов (URL, индексируемые/нет) и гистограмма глубины
- [ ] `v2` **Response Times** — гистограмма времени ответа
- [ ] `v3` **API** — прогресс и ошибки подключённых API
- [ ] `backlog` **Segments** — разрезы по сегментам
- [ ] `backlog` **Spelling & Grammar**, **Semantic Search** — панели орфографии и семантического поиска

---

## C. Настройки обхода

Справа от `→` — ключ профиля rb-spider (TOML, переопределяется `--set key=value`).

### Что обходить и сохранять (Spider > Crawl)

У каждого типа — раздельно `follow` (переходить/проверять) и `store` (записывать в БД), как Crawl/Store в SF.

- [x] `MVP` **Images** → `collect.images.follow` / `collect.images.store`
- [x] `MVP` **CSS** → `collect.css.follow` / `.store`
- [x] `MVP` **JavaScript** → `collect.js.follow` / `.store`
- [x] `MVP` **Media (video/audio)** → `collect.media.follow` / `.store`
- [x] `MVP` **Internal Hyperlinks** → `collect.internal_links.follow` / `.store`
- [x] `MVP` **External Links** → `collect.external_links.follow` / `.store`
- [x] `MVP` **Canonicals** (использовать для обнаружения URL) → `collect.canonicals.follow` / `.store`
- [x] `MVP` **Meta Refresh** → `collect.meta_refresh.follow` / `.store`
- [x] `MVP` **iframes** → `collect.iframes.follow` / `.store`
- [ ] `v2` **Pagination (rel next/prev)** → `collect.pagination.follow` / `.store`
- [ ] `v2` **Hreflang** → `collect.hreflang.follow` / `.store`
- [ ] `v2` **Mobile Alternate** → `collect.mobile_alternate.follow` / `.store`
- [ ] `v2` **Uncrawlable Links** (сохранять «ссылки» не в `<a href>`) → `collect.uncrawlable_links.store`
- [ ] `backlog` **AMP** → `collect.amp.follow` / `.store`
- [ ] `skip` **SWF (Flash)**
- [x] `MVP` **Check Links Outside of Start Folder** — проверять, но не обходить ссылки за пределами стартовой папки → `scope.check_outside_start_folder`
- [x] `MVP` **Crawl Outside of Start Folder** → `scope.crawl_outside_start_folder`
- [x] `MVP` **Crawl All Subdomains** — считать поддомены внутренними → `scope.all_subdomains`
- [x] `MVP` **Follow Internal / External "nofollow"** → `follow_nofollow.internal` / `follow_nofollow.external`
- [ ] `v2` **Crawl Invalid Links** — пробовать синтаксически битые href → `scope.crawl_invalid_links`
- [ ] `v2` **Crawl Linked XML Sitemaps** — найти sitemap через robots.txt или по списку → `sitemaps.discover`, `sitemaps.urls`

### Лимиты (Spider > Limits)

- [x] `MVP` **Limit Crawl Total** → `max_urls` / `--max-urls`
- [x] `MVP` **Limit Crawl Depth** → `limits.max_depth`
- [ ] `MVP` **Max Redirects to Follow** (#16) → `limits.max_redirects`
- [x] `MVP` **Max URL Length to Crawl** → `limits.max_url_length`
- [x] `MVP` **Max Links per URL to Crawl** → `limits.max_links_per_page`
- [ ] `v2` **Max Page Size (KB) to Crawl** → `limits.max_page_size_kb`
- [ ] `v2` **Limit URLs Per Crawl Depth** → `limits.max_urls_per_depth`
- [ ] `v2` **Limit Max Folder Depth** → `limits.max_folder_depth`
- [ ] `v2` **Limit Number of Query Strings** → `limits.max_query_params`
- [ ] `v2` **Limit Crawl Total Per Subdomain** → `limits.max_urls_per_subdomain`
- [ ] `v2` **Limit by URL Path** (шаблон → максимум страниц) → `limits.per_path`

### Рендеринг (Spider > Rendering)

- [ ] `MVP` **Rendering mode: Text Only / JavaScript** (#15) → `render = "never" | "always"`
- [ ] `v2` **Автовыбор рендеринга** → `render = "auto"` (AdaptivePlaywrightCrawler, см. spec.md)
- [ ] `MVP` **AJAX Timeout** (#15) — сколько ждать JS после загрузки → `render_options.wait_ms`
- [ ] `v2` **Window Size** (viewport, пресеты Googlebot desktop/mobile) → `render_options.viewport`
- [ ] `v2` **JavaScript Error Reporting** → `render_options.console_log`
- [ ] `v2` **Flatten Shadow DOM**, **Flatten iframes** → `render_options.flatten_shadow_dom`, `render_options.flatten_iframes`
- [ ] `v3` **Rendered Page Screenshots** → `render_options.screenshots`
- [ ] `backlog` **Old AJAX Crawling Scheme** (`_escaped_fragment_`)
- [ ] `backlog` **Archive Website** (сохранение сайта как папки или WARC)

### Дополнительно (Spider > Advanced)

- [x] `MVP` **Response Timeout** → `http.timeout`
- [ ] `v2` **5XX Response Retries** → `http.retries_5xx`
- [ ] `v2` **Ignore Non-Indexable URLs for Issues** — проверки контента только для индексируемых → `issues.indexable_only`
- [ ] `MVP` **Always Follow Redirects** (#16) (в режиме списка — до конечной цели) → `list.follow_redirects`
- [ ] `v2` **Respect Self Referencing Meta Refresh** → `issues.self_meta_refresh_non_indexable`
- [x] `MVP` **Extract Images From IMG SRCSET Attribute** → `collect.images.srcset`
- [ ] `v2` **Cookie Storage: session / persistent / none** → `http.cookies`
- [ ] `v2` **Ignore Paginated URLs for Duplicate Filters** → `duplicates.ignore_paginated`
- [ ] `v2` **Always Follow Canonicals** (в режиме списка) → `list.follow_canonicals`
- [ ] `v2` **Respect HSTS Policy** → `http.respect_hsts`
- [ ] `v2` **Crawl Fragment Identifiers** — считать `#fragment` отдельными URL → `scope.keep_fragments`
- [ ] `v2` **Perform HTML Validation** → `extract.html_validation`
- [ ] `v2` **Assume Pages are HTML** (нет Content-Type → HTML) → `http.assume_html`
- [ ] `skip` **Respect Noindex / Canonical / Next-Prev** — в SF только скрывают URL в интерфейсе; у нас это фильтры в `spider urls`
- [ ] `backlog` **Green Hosting Carbon Calculation**

### Пороги (Spider > Preferences)

- [x] `MVP` **Page Title: мин/макс символов** (30 / 60) → `thresholds.title_chars`
- [x] `MVP` **Meta Description: мин/макс символов** (70 / 155) → `thresholds.description_chars`
- [ ] `v2` **Title / Description: мин/макс пикселей** (200 / 561, 400 / 985) → `thresholds.title_px`, `thresholds.description_px`
- [x] `MVP` **Макс. длина H1 / H2** (70) → `thresholds.h1_chars`, `thresholds.h2_chars`
- [x] `MVP` **Макс. длина alt** (100) и **вес картинки КБ** (100) → `thresholds.alt_chars`, `thresholds.image_kb`
- [x] `MVP` **Порог Low Content** (200 слов) → `thresholds.min_words`
- [x] `MVP` **High Crawl Depth, High Internal / External Outlinks** → `thresholds.crawl_depth`, `thresholds.internal_outlinks`, `thresholds.external_outlinks`
- [x] `MVP` **Список неинформативных анкоров** → `thresholds.non_descriptive_anchors`
- [ ] `v2` **Макс. длина URL** (115) → `thresholds.url_chars`

### Контент (Config > Content)

- [x] `MVP` **Content Area** — какие элементы учитывать в тексте (по умолчанию `<body>` без `<nav>` и `<footer>`) → `content.include` / `content.exclude`
- [ ] `v2` **Exact duplicates (hash)** + **Only Check Indexable Pages** → `duplicates.exact`, `duplicates.indexable_only`
- [ ] `v2` **Near Duplicates** + порог сходства (90 %) → `duplicates.near`, `duplicates.near_threshold`
- [ ] `backlog` **Spelling & Grammar** (языки, правила, словарь)
- [ ] `backlog` **Embeddings** (Semantic Similarity, Low Relevance через AI-провайдера)

### robots.txt

- [x] `MVP` **Respect / Ignore robots.txt** → `respect_robots` / `--ignore-robots`
- [x] `MVP` **Ignore robots.txt but report status** — обходить, но отмечать, что было бы заблокировано → `robots.mode = "report"`
- [ ] `v2` **Show Internal URLs Blocked by Robots.txt** (+ совпавшая строка robots.txt) → `robots.show_internal_blocked`
- [ ] `v2` **Show External URLs Blocked by Robots.txt** → `robots.show_external_blocked`
- [ ] `v2` **Custom Robots** — подменить robots.txt для обхода (тест правок) → `robots.custom`

### URL и домены

- [x] `MVP` **Include / Exclude** (regex) → `include`, `exclude`
- [ ] `v2` **URL Rewriting: Remove Parameters** → `rewrite.remove_params`
- [ ] `v2` **URL Rewriting: Regex Replace** → `rewrite.regex`
- [ ] `v2` **URL Rewriting: Lowercase Discovered URLs, Percent Encoding Mode** → `rewrite.lowercase`, `rewrite.percent_encoding`
- [ ] `v2` **CDNs** — домены, которые считать внутренними → `scope.cdns`

### Запросы

- [x] `MVP` **Speed: Max Threads** → `concurrency` / `--concurrency`
- [x] `MVP` **Speed: Max URI/s** → `max_rps`
- [x] `MVP` **User-Agent: пресеты и своя строка** → `user_agent` (пресеты `googlebot`, `googlebot-smartphone`, `yandexbot`…)
- [x] `MVP` **Robots User-Agent** — чью группу правил robots.txt соблюдать → `robots.user_agent`
- [x] `MVP` **HTTP Header** — произвольные заголовки запроса → `headers`
- [x] `MVP` **Proxy** → `proxy` / `--proxy` (в SF — один прокси; у нас ротация через Crawlee)
- [ ] `v2` **Authentication: Basic / Digest** → `auth.basic` (пароль — в keychain)
- [ ] `v2` **Trusted Certificates** (свои корневые сертификаты для MITM-прокси) → `http.ca_bundle`
- [ ] `backlog` **Authentication: Forms Based** (вход через браузер, cookies для обхода)

### Пользовательские правила (Config > Custom)

- [ ] `v2` **Custom Search** — «содержит / не содержит» текст или regex в HTML, тексте, элементе → `custom.search`
- [ ] `v2` **Custom Extraction** — XPath, CSS, regex; вывод элемент / inner HTML / текст / значение функции → `custom.extract`
- [ ] `v2` **Link Positions** — правила «XPath ссылки → зона (nav, footer, content…)» → `custom.link_positions`
- [ ] `backlog` **Custom JavaScript** — пользовательские JS-сниппеты на каждой странице (извлечение и действия)
- [ ] `backlog` **Segments** — сегменты URL по правилам

### Анализ после обхода и профили

- [x] `MVP` **Crawl Analysis** — сайтовые проверки (дубли, unlinked canonical, non-indexable inlinks…) считаются SQL после обхода автоматически
- [ ] `MVP` **Повторный анализ без переобхода** (после смены порогов) — например, `spider analyze <crawl_id>`
- [ ] `v2` **Crawl Analysis: полный список пунктов** (Pagination, Hreflang return links и др.) (не подтверждено)
- [x] `MVP` **Configuration profiles** — сохранение/загрузка настроек → профили `.spider/profiles/*.toml`, `extends` (см. раздел G)
- [ ] `v2` **Compare config** — какие элементы учитывать при сравнении обходов → `compare.fields`
- [ ] `v3` **URL Mapping** при сравнении (regex «старый URL → новый», staging vs production) (не подтверждено)

### Системные настройки SF

- [ ] `skip` **Storage Mode: Database / Memory** — по прототипу #3 не нужен: результаты всегда на диске, скорость задаёт очередь (spec, раздел 2)
- [ ] `MVP` **Crawl Retention** — автоудаление старых обходов → `spider crawls prune` (см. раздел G)
- [ ] `skip` **Memory Allocation** (JVM heap) — не нужен в Python
- [ ] `skip` **User Interface, Language, Notifications, Auto Updates** — только для GUI
- [ ] `backlog` **MCP Server** — краулер как MCP-сервер для ИИ-агентов

---

## D. Режимы

- [x] `MVP` **Spider** — обход сайта от стартового URL по ссылкам → `spider crawl <url>`
- [ ] `MVP` **List** — обход списка URL из файла (глубина 0; для миграций вместе с Always Follow Redirects) → `spider crawl --list urls.txt`
- [ ] `v2` **List: загрузка из XML sitemap, CSV, Excel** — извлечь URL из файла любого из этих форматов
- [ ] `v2` **Compare** — сравнение двух обходов: добавлено / новое / удалено / пропало по каждой проверке + Change Detection → `spider compare <id1> <id2>`
- [ ] `v3` **APIs** — только загрузить данные API (GSC, PSI…) по списку URL, без обхода
- [ ] `backlog` **SERP** — посчитать длины и ширину в пикселях для загруженных title/description без обхода
- [ ] `v3` **Staging vs production** — сравнение двух окружений с сопоставлением URL

### Управление обходами

- [x] `MVP` **Start / Resume** — запуск и продолжение прерванного обхода → `spider crawl`, `spider crawls resume <id>`
- [ ] `MVP` **Pause** — остановка с возможностью продолжить (Ctrl+C или сигнал фоновому процессу)
- [ ] `MVP` **Хранение обходов** — список, просмотр, удаление, проекты → `spider crawls list|show|delete`, `spider projects`
- [x] `MVP` **Снимок конфига обхода** — итоговый конфиг сохраняется в `crawls`
- [ ] `v2` **Re-spider selected URLs** — переобойти выбранные URL в существующем обходе
- [ ] `backlog` **Lock crawl / rename / duplicate** — защита обхода от удаления, переименование, копия
- [ ] `backlog` **Экспорт/импорт обхода файлом** (аналог `.seospider`)
- [ ] `backlog` **Scheduling** — по расписанию; закрывается cron + `spider crawl --profile …`
- [ ] `skip` **UI**: перетаскиваемые вкладки и колонки, Focus Mode, панели, поиск в интерфейсе

---

## E. Экспорт и отчёты

### Экспорт

- [ ] `MVP` **Экспорт вкладки / фильтра** → `spider urls --issue <code> --json`, `spider export --format csv|json`
- [x] `MVP` **Экспорт деталей URL** (inlinks, outlinks, картинки) → `spider links <url> --in|--out --json`
- [ ] `MVP` **Форматы CSV и JSON**
- [ ] `v2` **Формат Excel (.xlsx)**
- [ ] `v2` **Multi-Export** — много вкладок и отчётов за один вызов, пресеты
- [ ] `skip` **Google Sheets / Google Drive**
- [ ] `skip` **Export for Looker Studio**

### Bulk Export (массовые выгрузки)

- [ ] `MVP` **Links: All Inlinks, All Outlinks, All Anchor Text, External Links**
- [ ] `MVP` **Response Codes: inlinks к URL с каждым кодом** (например, все ссылки на 404)
- [ ] `MVP` **Issues: All** — все сработавшие проверки со списками URL
- [ ] `v2` **Links: выгрузки по проблемам** (nofollow, без анкора, неинформативный анкор, localhost…)
- [ ] `v2` **Queued URLs** — очередь необойдённых URL
- [ ] `v2` **Path Type** — ссылки по типу пути: абсолютные, протокол-относительные, от корня, относительные
- [ ] `v2` **Security, Canonicals, Directives, Images, Content, JavaScript, Structured Data, Sitemaps, Custom Search, Custom Extraction** — выгрузки по фильтрам вкладок (в т.ч. все пары почти-дублей, RDF-тройки разметки)
- [ ] `v2` **Web: All Page Source, All Page Text** (нужен `--store-html`)
- [ ] `v2` **Web: All HTTP Request / Response Headers, All Cookies**
- [ ] `v3` **Web: Screenshots**
- [ ] `v3` **URL Inspection: Rich Results, Referring Pages, Sitemaps** (данные GSC)
- [ ] `backlog` **Web: Archived Website, All PDF Documents, All PDF Content**
- [ ] `backlog` **AMP, Accessibility, AI** — выгрузки соответствующих вкладок

### Отчёты (Reports)

- [ ] `MVP` **Crawl Overview** — итоги: найдено / заблокировано / обойдено, типы содержимого, коды ответа
- [ ] `MVP` **Issues Overview** — сводка всех проблем → `spider issues` (не подтверждено)
- [x] `MVP` **Redirects: All Redirects** — все редиректы
- [x] `MVP` **Redirects: Redirect Chains** — цепочки из 2+ прыжков и петли, тип (HTTP / JS / meta refresh)
- [x] `MVP` **Redirects: Redirects to Errors** — редиректы на заблокированные, неотвечающие, 4xx, 5xx
- [ ] `v2` **Redirects: Redirect & Canonical Chains** — цепочки с учётом canonical
- [ ] `v2` **Canonicals: Canonical Chains, Non-Indexable Canonicals**
- [ ] `v2` **Pagination: Non-200, Unlinked**
- [ ] `v2` **Hreflang: All, Non-200, Unlinked, Missing Return, Inconsistent, Non-Canonical, Noindex Return Links**
- [ ] `v2` **Insecure Content** — HTTPS-страницы с HTTP-ссылками и ресурсами
- [ ] `v2` **SERP Summary** — URL, title, description, длины и ширина в пикселях
- [ ] `v2` **Orphan Pages** — URL из sitemap, не найденные обходом (источники GA/GSC — позже)
- [ ] `v2` **Structured Data: Validation Errors & Warnings (Summary), Google Rich Results Features (Summary)**
- [ ] `v2` **JavaScript: Chrome Console Log Summary**
- [ ] `v2` **HTTP Header Summary, Cookie Summary** — уникальные заголовки / cookies × число URL
- [ ] `v2` **Crawl Path Report** — кратчайший путь обнаружения URL
- [ ] `v3` **PageSpeed: Opportunities Summary, CSS / JavaScript Coverage Summary**
- [ ] `v3` **Mobile** — выгрузки с деталями Lighthouse
- [ ] `backlog` **Segments Overview** (не подтверждено)
- [ ] `backlog` **Accessibility Violations Summary**

### Генерация sitemap (через rb-sitemap-xml)

- [ ] `v2` **XML Sitemap** — индексируемые 200-страницы; опционально noindex / canonicalised / пагинация / PDF; lastmod, priority, changefreq; разбиение по 49 999 URL + индексный sitemap → spider отдаёт список URL, генерирует `sitemap-xml build`
- [ ] `v2` **Image Sitemap** — страницы с картинками, картинки с кодом 200
- [ ] `backlog` **Sitemap по сегментам**

### Визуализации

- [ ] `v3` **Crawl Diagram / Tree Graph** — граф обхода (force-directed, дерево), цвет по индексируемости и метрикам
- [ ] `v3` **Directory Tree Diagram / Graph** — граф по каталогам
- [ ] `v3` **Экспорт визуализаций в SVG**
- [ ] `backlog` **3D-графы**
- [ ] `backlog` **Word clouds** (анкоры, текст страниц)
- [ ] `backlog` **Content Cluster Diagram** (кластеры по эмбеддингам)

### Прочий анализ

- [ ] `v3` **Link Score** — внутренний PageRank 0–100 после обхода
- [ ] `v2` **Readability** — Flesch Reading Ease
- [ ] `v2` **Robots.txt tester** — проверить, разрешён ли URL, с подменённым robots.txt
- [ ] `v2` **SERP snippet emulator** — предпросмотр сниппета (без редактирования в UI)
- [ ] `backlog` **N-grams**
- [ ] `backlog` **Semantic search / similarity** (эмбеддинги)
- [ ] `backlog` **Carbon footprint / rating** — CO₂ на загрузку страницы (шкала рейтинга — не подтверждено)

---

## F. Интеграции

- [ ] `MVP` **Интерфейс обогатителей (enrichers)** — плагины через entry points, пишут в `url_metrics` (реализаций в MVP нет)
- [ ] `v3` **Google Search Console** — Search Analytics (клики, показы, CTR, позиция), URL Inspection API; на основе пакета `google-search-console`
- [ ] `v3` **Яндекс.Вебмастер** — аналог GSC для Яндекса; на основе пакета `yandex-webmaster` (в SF нет)
- [ ] `v3` **PageSpeed Insights** — CrUX (полевые Core Web Vitals) + Lighthouse (лабораторные), mobile/desktop
- [ ] `v3` **Lighthouse локально** — без API, работает за авторизацией
- [ ] `v3` **Majestic / Ahrefs / Moz** — внешние ссылочные метрики по URL / поддомену / домену
- [ ] `backlog` **AI: OpenAI, Gemini, Ollama, Anthropic** — промпты к каждой странице, эмбеддинги
- [ ] `skip` **Google Analytics 4**
- [ ] `skip` **Looker Studio / Data Studio**
- [ ] `skip` **Google Sheets / Google Drive**
- [ ] `skip` **Email-уведомления** (Outlook, Gmail, SMTP)

---

## G. Наше, чего нет в SF

### CLI и работа с данными

- [ ] `MVP` **Drill-down для агентов** — `spider issues` → `spider urls --issue` → `spider url` / `spider links`; у каждой команды таблица для человека и `--json`
- [ ] `MVP` **`spider status`** — прогресс и итоги обхода из БД (в т.ч. для фонового)
- [ ] `MVP` **`spider query "SELECT …"`** — произвольный SQL по данным обхода
- [ ] `MVP` **`spider crawls prune --keep-last N | --older-than 90d`** — чистка старых обходов
- [ ] `MVP` **`spider crawls delete <id>…`, `spider projects delete`** — с подтверждением, `--yes`, `--dry-run`
- [ ] `MVP` **`spider db info | migrate | vacuum`** — состояние БД, миграции Alembic, сжатие файла
- [x] `MVP` **`--detach`** — обход фоновым процессом, статус в БД
- [x] `MVP` **Своя очередь обхода** — в памяти + фильтр виденных URL, снимок в SQLite в одной транзакции с результатами; возобновление без потерь
- [x] `MVP` **`--store-html`** — хранить HTML (zstd) в отдельном SQLite-файле; по умолчанию только md5
- [ ] `MVP` **Статус «не проверялось»** — проверка без нужных данных (сбор выключен) не выдаёт ложное «ок»
- [ ] `MVP` **Переключаемый HTTP-клиент** → `http.client = "impit" | "curl"`
- [ ] `v2` **Удалённые БД Postgres / MySQL** — DSN в keychain

### Конфиг и профили

- [x] `MVP` **8 слоёв конфига** — встроенные → глобальный → проект → профиль → `--config` → env `SPIDER_…` → флаги → `--set`
- [x] `MVP` **`--set dotted.key=value`** — переопределить любой ключ
- [x] `MVP` **`spider config show`** — итоговый конфиг с источником каждого значения
- [x] `MVP` **`spider config validate <file>`**
- [x] `MVP` **`spider config schema`** — JSON Schema конфига для агентов
- [x] `MVP` **`spider profiles list | show | init [--from preset]`** — профили с наследованием `extends`; шаблон с комментариями
- [x] `MVP` **Встроенные пресеты** — `default`, `googlebot`, `yandexbot`, `fast`

### Документация и агенты

- [ ] `MVP` **`docs/profiles.md`** — справочник всех ключей (генерируется из схемы) + рецепты: быстрый аудит, миграция по списку, JS-сайт, прокси, только битые ссылки, большой магазин
- [ ] `MVP` **Скилл для ИИ-агентов** — как выбрать/составить профиль и какие команды звать для анализа (по образцу `serp`)

### Тестирование и производительность

- [ ] `MVP` **Синтетический полигон в pytest** — страница-ловушка на каждую проверку из этого файла; покрытие ≥ 90 %
- [ ] `MVP` **`bench/gen_site.py`** — генератор статического сайта 10k/50k/100k страниц (seed, категории, пагинация, перелинковка) для замеров скорости и памяти; деплой через `hostme`

### Доработки rb-sitemap-xml

- [ ] `v2` **Метаданные URL** — отдавать `lastmod`, `changefreq`, `priority`, файл-источник
- [ ] `v2` **Async API**
- [ ] `v2` **Команда `sitemap-xml build`** — генерация sitemap по списку индексируемых URL от spider
