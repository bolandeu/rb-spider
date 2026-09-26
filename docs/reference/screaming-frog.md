# Screaming Frog SEO Spider — raw feature & issue checklist

Source: https://www.screamingfrog.co.uk/seo-spider/issues/ (+ each issue sub-page), https://www.screamingfrog.co.uk/seo-spider/user-guide/configuration/, /user-guide/general/, /user-guide/tabs/. Fetched 2026-09-26 (SEO Spider v24.3).

Legend: **Type** = Issue (error, fix it) / Warning (check it) / Opportunity (possible improvement). **Priority** = SF-assigned High / Medium / Low. "Def" = first sentence of the SF issue page; "Trigger" = first sentence of its "What Triggers This Issue" section.

Total issues in library: **320** across 24 groups.

## Contents

1. Part 1 — Issues library (by tab)
2. Part 2 — Tabs & all filters (incl. non-issue filters), lower-window tabs
3. Part 3 — Configuration options
4. Part 4 — Modes
5. Part 5 — Reports, exports, other output features
6. Appendix — columns per tab


---

# Part 1 — Issues library


## Response Codes (15)

_HTTP response status codes indicate whether an HTTP request made during a crawl has been successfully completed. Find issues related to URLs that are blocked from being crawled, return a no response, redirect, client or server error._

- **[Internal No Response](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-no-response/)** — Issue · High — Internal URLs with no response returned from the server. Usually due to a malformed URL, connection timeout , connection error , or connection refused . _Trigger:_ This issue is triggered when an internal URL does not respond with an HTTP response at all.
- **[Internal Client Error (4XX)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-client-error-4xx/)** — Issue · High — Internal URLs with a client-side error. _Trigger:_ This issue is triggered when an internal URL responds with a client-side error (4xx response code), such as a 404 ‘Page Not Found’.
- **[Internal Server Error (5XX)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-server-error-5xx/)** — Issue · High — Internal URLs where the server failed to fulfill an apparently valid request. This can include common responses such as 500 Internal Server Errors, and 503 Service Unavailable. _Trigger:_ This issue is triggered when an internal URL responds with a server error (5xx response code), such as a 503 ‘Service Unavailable’.
- **[Internal Redirect Loop](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-redirect-loop/)** — Issue · High — Internal URLs that redirect to another URL, which also then redirects. This can occur multiple times in a row, each redirect is referred to as a ‘hop’. _Trigger:_ This issue is triggered when an internal URL returns a 3xx response code, that also returns a 3xx response code.
- **[Internal Blocked by Robots.txt](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-blocked-by-robots-txt/)** — Warning · High — Internal URLs blocked by the site’s robots.txt. This means they cannot be crawled and is a critical issue if you want the page content to be crawled and indexed by search engines. _Trigger:_ The issue is triggered when directives within the robots.txt match the URLs in question.
- **[Internal Blocked Resource](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-blocked-resource/)** — Warning · High — Internal resources (such as images, JavaScript and CSS) that are blocked from rendering by robots.txt or an error. _Trigger:_ This issue is triggered when internal resources match directives within the robots.txt.
- **[Internal Redirect Chain](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-redirect-chains/)** — Warning · Medium — Internal URLs that redirect to another URL, which also then redirects. This can occur multiple times in a row, each redirect is referred to as a ‘hop’. _Trigger:_ This issue is triggered when an internal URL returns a 3xx response code, that also returns a 3xx response code.
- **[External Blocked Resource](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/external-blocked-resource/)** — Warning · Medium — External resources (such as images, JavaScript and CSS) that are blocked from rendering by robots.txt or an error. _Trigger:_ This issue is triggered when external resources match directives within the robots.txt.
- **[Internal Redirection (3XX)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-redirection-3xx/)** — Warning · Low — Internal URLs which redirect to another URL. These will include server-side redirects, such as 301 or 302 redirects (and more). _Trigger:_ This issue is triggered when an internal URL returns a 3xx response code, indicating that it redirects to another URL.
- **[Internal Redirection (Meta Refresh)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-redirection-meta-refresh/)** — Warning · Low — Internal URLs with a meta refresh. This is a client-side redirect which instructs the browser to ‘refresh’ to a URL with a specific time. _Trigger:_ This issue is triggered when an internal URL has a meta refresh attribute, indicating that it ‘refreshes’ to a URL with a specific time. <head> <meta http-equiv="refresh" content="30"> </head>
- **[Internal Redirection (HTTP Refresh)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-redirection-http-refresh/)** — Warning · Low — Internal URLs with an HTTP refresh. This instructs the browser to ‘refresh’ to a URL with a specific time. _Trigger:_ This issue is triggered when an internal URL has an HTTP refresh in the HTTP header, indicating that it ‘refreshes’ to a URL with a specific time.
- **[Internal Redirection (JavaScript)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/internal-redirection-javascript/)** — Warning · Low — Internal URLs with a JavaScript redirect to another URL. _Trigger:_ This issue is triggered when an internal URL has a JavaScript redirect to another URL. window.location.href = 'https://www.screamingfrog.co.uk/';
- **[External No Response](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/external-no-response/)** — Warning · Low — External URLs with no response returned from the server. Usually due to a malformed URL, connection timeout, connection error, or connection refused. _Trigger:_ This issue is triggered when an external URL responds with a status code 0, such as a connection timeout, connection error, connection refused or DNS lookup failed.
- **[External Client Error (4XX)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/external-client-error-4xx/)** — Warning · Low — External URLs with a client-side error. _Trigger:_ This issue is triggered when an external URL responds with a client-side error (4xx response code), such as a 404 ‘Page Not Found’.
- **[External Server Error (5XX)](https://www.screamingfrog.co.uk/seo-spider/issues/response-codes/external-server-error-5xx/)** — Warning · Low — External URLs where the server failed to fulfill an apparently valid request. This can include common responses such as 500 Internal Server Errors and 503 Service Unavailable. _Trigger:_ This issue is triggered when an external URL responds with a server error (5xx response code), such as a 503 ‘Service Unavailable’.

## Security (12)

_Website security is important to protect users and reduce risk from common threats. Find issues related to basic security best practices, such as HTTPS, mixed content, and HTTP security headers._

- **[HTTP URLs](https://www.screamingfrog.co.uk/seo-spider/issues/security/http-urls/)** — Issue · High — HTTP URLs that are encountered in the crawl. _Trigger:_ This issue is triggered for any internal URL found in a crawl that is linked to using HTTP instead of HTTPS.
- **[Mixed Content](https://www.screamingfrog.co.uk/seo-spider/issues/security/mixed-content/)** — Issue · High — HTML pages loaded over a secure HTTPS connection that have resources such as images, JavaScript or CSS that are loaded via an insecure HTTP connection. _Trigger:_ This issue is triggered when a HTML page loaded over a secure HTTPS connection contains resources such as images, JavaScript or CSS, that are loaded via an insecure HTTP connection.
- **[Form URL Insecure](https://www.screamingfrog.co.uk/seo-spider/issues/security/form-url-insecure/)** — Issue · High — HTML pages that contain a form with an action attribute URL that is insecure (HTTP). _Trigger:_ This issue is triggered when a HTML page contains a form with an action attribute URL that is insecure (HTTP).
- **[Form On HTTP URL](https://www.screamingfrog.co.uk/seo-spider/issues/security/form-on-http-url/)** — Issue · High — This indicates that a form is on an HTTP page. Any data entered into the form, including usernames and passwords is not secure. _Trigger:_ This issue is triggered when a form is on a HTTP page.
- **[Missing HSTS Header](https://www.screamingfrog.co.uk/seo-spider/issues/security/missing-hsts-header/)** — Warning · Low — URLs that are missing the HSTS response header. The HTTP Strict-Transport-Security response header (HSTS) instructs browsers that it should only be accessed using HTTPS, rather than HTTP. _Trigger:_ This issue is triggered when a URL is missing the HSTS response header.
- **[Unsafe Cross Origin Links](https://www.screamingfrog.co.uk/seo-spider/issues/security/unsafe-cross-origin-links/)** — Warning · Low — URLs that link to external websites using the target=”_blank” attribute (to open in a new tab), without using rel=”noopener” (or rel=”noreferrer” ) at the same time. _Trigger:_ This issue is triggered when a URL contains links to external websites using the target=”_blank” attribute (to open in a new tab), without using rel=”noopener” (or rel=”noreferrer” ) at the same time.
- **[Protocol-Relative Resource Links](https://www.screamingfrog.co.uk/seo-spider/issues/security/protocol-relative-resource-links/)** — Warning · Low — URLs that load resources such as images, JavaScript and CSS using protocol-relative links. _Trigger:_ This issue is triggered when a URL that loads resources such as images, JavaScript and CSS uses protocol-relative links.
- **[Missing Content-Security-Policy Header](https://www.screamingfrog.co.uk/seo-spider/issues/security/missing-content-security-policy-header/)** — Warning · Low — URLs that are missing the Content-Security-Policy response header. This header allows a website to control which resources are loaded for a page. _Trigger:_ This issue is triggered when a URL is missing the Content-Security-Policy response header.
- **[Missing X-Content-Type-Options Header](https://www.screamingfrog.co.uk/seo-spider/issues/security/missing-x-content-type-options-header/)** — Warning · Low — URLs that are missing the ‘X-Content-Type-Options’ response header with a nosniff value. _Trigger:_ This issue is triggered when a URL is missing the ‘X-Content-Type-Options’ response header with a nosniff value.
- **[Missing X-Frames-Options Header](https://www.screamingfrog.co.uk/seo-spider/issues/security/missing-x-frames-options-header/)** — Warning · Low — URLs missing an X-Frame-Options response header with a DENY or SAMEORIGIN value. _Trigger:_ This issue is triggered when a URL is missing the ‘X-Frame-Options’ HTTP header with a DENY or SAMEORIGIN value.
- **[Missing Secure Referrer-Policy Header](https://www.screamingfrog.co.uk/seo-spider/issues/security/missing-secure-referrer-policy-header/)** — Warning · Low — URLs missing no-referrer-when-downgrade , strict-origin-when-cross-origin , no-referrer or strict-origin policies in the Referrer-Policy header. _Trigger:_ This issue is triggered when a URL is missing no-referrer-when-downgrade , strict-origin-when-cross-origin , no-referrer or strict-origin ‘ policies in the Referrer-Policy header.
- **[Bad Content Type](https://www.screamingfrog.co.uk/seo-spider/issues/security/bad-content-type/)** — Warning · Low — This indicates any URLs where the actual content type does not match the content type set in the header. _Trigger:_ This issue is triggered when a URL contains content that does not match the content type set in the header.

## URL (11)

_Ensuring a website has logical and relevant URLs is vital for users and search engines in understanding website structure, and the content of a page. Find issues non-optimal formats, or URLs that shouldn't be discoverable._

- **[Multiple Slashes](https://www.screamingfrog.co.uk/seo-spider/issues/url/multiple-slashes/)** — Issue · Low — URLs that have multiple forward slashes in the path ( example.com/page1// ). _Trigger:_ This issue is triggered when a URL has multiple forward slashes in the path, excluding protocol slashes (https://).
- **[Contains A Space](https://www.screamingfrog.co.uk/seo-spider/issues/url/contains-a-space/)** — Issue · Low — URLs that contain a space. These are considered unsafe and could cause the link to be broken when sharing the URL. Hyphens should be used as word separators instead of spaces. _Trigger:_ This issue is triggered when a URL contains a space.
- **[Broken Bookmark](https://www.screamingfrog.co.uk/seo-spider/issues/url/broken-bookmark/)** — Issue · Low — URLs that have a broken bookmark (also known as ‘named anchors’, ‘jump links’, and ‘skip links’) that link users to a specific part of a webpage using an ID attribute in the HTML and append a fragment (#) and the ID name to the URL. _Trigger:_ This issue is triggered when a URL has a broken bookmark/named anchor which fails to direct the user to the intended section of the webpage.
- **[Non ASCII Characters](https://www.screamingfrog.co.uk/seo-spider/issues/url/non-ascii-characters/)** — Warning · Low — URLs with characters outside of the ASCII character-set. Standards outline that URLs can only be sent using the ASCII character-set and some users may have difficulty with subtleties of characters outside this range. _Trigger:_ This issue is triggered when a URL contains characters outside of the ASCII character-set.
- **[Uppercase](https://www.screamingfrog.co.uk/seo-spider/issues/url/uppercase/)** — Warning · Low — URLs that have uppercase characters within them. URLs are case sensitive, so as best practice generally URLs should be lowercase, to avoid any potential mix ups and duplicate URLs. _Trigger:_ This issue is triggered when a URL includes uppercase characters.
- **[Repetitive Path](https://www.screamingfrog.co.uk/seo-spider/issues/url/repetitive-path/)** — Warning · Low — URLs that have repetitive paths or subfolders within the string ( example.com/example/example/ ). _Trigger:_ This issue is triggered when a URL contains repetitive paths or subfolders.
- **[Internal Search](https://www.screamingfrog.co.uk/seo-spider/issues/url/internal-search/)** — Warning · Low — URLs that might be part of the websites internal search function. _Trigger:_ This issue is triggered when a URL appears to be part of the website’s internal search function.
- **[Parameters](https://www.screamingfrog.co.uk/seo-spider/issues/url/parameters/)** — Warning · Low — URLs that include parameters such as ‘?’ or ‘&’. _Trigger:_ This issue is triggered when a URL includes parameters such as ‘?’ or ‘&’.
- **[GA Tracking Parameters](https://www.screamingfrog.co.uk/seo-spider/issues/url/ga-tracking-parameters/)** — Warning · Low — URLs that contain Google Analytics tracking parameters. _Trigger:_ This issue is triggered when a URL contains Google Analytics tracking parameters such as utm= , _ga= , or _gl= .
- **[Underscores](https://www.screamingfrog.co.uk/seo-spider/issues/url/underscores/)** — Opportunity · Low — URLs with underscores, which are not always seen as word separators by search engines. _Trigger:_ This issue is triggered when a URL contains underscores (_).
- **[Over 115 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/url/over-115-characters/)** — Opportunity · Low — URLs that are more than 115 characters in length. This is generally not an issue, however research has shown that users prefer shorter, concise URL strings. _Trigger:_ This issue is triggered when a URL exceeds 115 characters in length.

## Page Titles (9)

_Relevant and descriptive page titles are essential, as they help both users and search engines understand the purpose of a page. Find issues related to missing, duplicate, long or even multiple page titles._

- **[Missing](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/page-title-missing/)** — Issue · High — Pages which have a missing page title element, the content is empty, or has a whitespace. _Trigger:_ This issue is triggered when a page has a missing title element, the content is empty, or contains only whitespace.
- **[Multiple](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/multiple/)** — Issue · High — Pages which have multiple page titles. There should only be a single page title element for each page. Multiple page titles are often caused by multiple conflicting plugins or modules in CMS. _Trigger:_ This issue is triggered when a page has multiple page title elements.
- **[Outside <head>](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/page-title-outside-head/)** — Issue · High — Pages with a <title> element that is outside of the <head> element in the HTML. _Trigger:_ This issue is triggered when a page has a <title> element outside of the <head> element in the HTML.
- **[Duplicate](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/duplicate/)** — Opportunity · Medium — Pages which have duplicate page titles. It’s really important to have distinct and unique page titles for every page. _Trigger:_ This issue is triggered when multiple URLs have the same page title.
- **[Over 60 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/over-60-characters/)** — Opportunity · Medium — Pages which have page titles over 60 characters in length. Characters over this limit might be truncated in Google’s search results and carry less weight in scoring. _Trigger:_ This issue is triggered when a page has a title exceeding 60 characters in length.
- **[Below 30 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/below-30-characters/)** — Opportunity · Medium — Pages which have page titles under 30 characters in length. This isn’t necessarily an issue, but it does indicate there might be room to target additional keywords or communicate your USPs. _Trigger:_ This issue is triggered when a page has a title under 30 characters in length.
- **[Over 561 Pixels](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/over-561-pixels/)** — Opportunity · Medium — Pages which have page titles over Google’s estimated pixel length limit for titles in search results. _Trigger:_ This issue is triggered when a page has a title that exceeds Google’s estimated pixel length limit for titles in search results.
- **[Below 200 Pixels](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/below-200-pixels/)** — Opportunity · Medium — Pages which have page titles much shorter than Google’s estimated pixel length limit. _Trigger:_ This issue is triggered when a page has a title much shorter than Google’s estimated pixel length limit.
- **[Same as H1](https://www.screamingfrog.co.uk/seo-spider/issues/page-titles/same-as-h1/)** — Opportunity · Low — Page titles which match the <h1> on the page exactly. _Trigger:_ This issue is triggered when a page title matches the h1 heading on the page exactly.

## Meta Description (8)

_Meta descriptions can be used in search engine result snippets, so writing a good meta description can be helpful for users and drive more clicks to a website. Find issues related to missing, duplicate, long or even multiple meta descriptions._

- **[Multiple](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/meta-description-multiple/)** — Issue · Medium — Pages which have multiple meta descriptions. There should only be a single meta description for each page. _Trigger:_ This issue is triggered when a page has multiple meta descriptions.
- **[Outside <head>](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/meta-description-outside-head/)** — Issue · Medium — Pages with a meta description that is outside of the <head> element in the HTML. The meta description should be within the <head> element, or search engines may ignore it. _Trigger:_ This issue is triggered when a page has a meta description outside of the <head> element in the HTML.
- **[Missing](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/meta-description-missing/)** — Opportunity · Low — Pages which have a missing meta description, the content is empty or has a whitespace. _Trigger:_ This issue is triggered when a page has a missing meta description, the content is empty, or contains only whitespace.
- **[Duplicate](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/meta-description-duplicate/)** — Opportunity · Low — Pages which have duplicate meta descriptions. It’s really important to have distinct and unique meta descriptions that communicate the benefits and purpose of each page. _Trigger:_ This issue is triggered when pages have duplicate meta descriptions.
- **[Over 155 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/over-155-characters/)** — Opportunity · Low — Pages which have meta descriptions over 155 characters in length. Characters over this limit might be truncated in Google’s search results. _Trigger:_ This issue is triggered when a page has a meta description exceeding 155 characters in length.
- **[Below 70 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/below-70-characters/)** — Opportunity · Low — Pages which have meta descriptions below 70 characters in length. This isn’t strictly an issue, but an opportunity. _Trigger:_ This issue is triggered when a page has a meta description shorter than 70 characters in length.
- **[Over 985 Pixels](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/over-985-pixels/)** — Opportunity · Low — Pages which have meta descriptions over Google’s estimated pixel length limit for snippets. _Trigger:_ This issue is triggered when a page has a meta description that exceeds Google’s estimated pixel length limit for snippets.
- **[Below 400 Pixels](https://www.screamingfrog.co.uk/seo-spider/issues/meta-description/below-400-pixels/)** — Opportunity · Low — Pages which have meta descriptions much shorter than Google’s estimated pixel length limit. _Trigger:_ This issue is triggered when a page has a meta description much shorter than Google’s estimated pixel length limit.

## H1 (6)

_Headings help provide structure and organisation to a web page, and can allow users and search engines to better understand the content. The h1 should describe the main title and purpose of the page. Find issues related to missing, duplicate, long or non-sequential h1's._

- **[Missing](https://www.screamingfrog.co.uk/seo-spider/issues/h1/h1-missing/)** — Issue · Medium — Pages which have a missing <h1> , the content is empty or has a whitespace. _Trigger:_ This issue is triggered when a page has a missing <h1> tag, the content is empty, or contains only whitespace.
- **[Multiple](https://www.screamingfrog.co.uk/seo-spider/issues/h1/h1-multiple/)** — Warning · Medium — Pages which have multiple <h1> s. _Trigger:_ This issue is triggered when a page contains multiple <h1> tags.
- **[Alt Text in h1](https://www.screamingfrog.co.uk/seo-spider/issues/h1/alt-text-in-h1/)** — Warning · Low — Pages which have image alt text within an <h1> . _Trigger:_ This issue is triggered when a page includes image alt text within an <h1> tag.
- **[Non-sequential](https://www.screamingfrog.co.uk/seo-spider/issues/h1/h1-non-sequential/)** — Warning · Low — Pages with an <h1> that is not the first heading on the page. _Trigger:_ This issue is triggered when a page’s <h1> is not the first heading element on the page.
- **[Duplicate](https://www.screamingfrog.co.uk/seo-spider/issues/h1/h1-duplicate/)** — Opportunity · Low — Pages which have duplicate <h1>s . It’s important to have distinct, unique and useful main headings. _Trigger:_ This issue is triggered when pages have duplicate <h1> tags.
- **[Over 70 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/h1/h1-over-70-characters/)** — Opportunity · Low — Pages which have <h1> s over 70 characters in length. _Trigger:_ This issue is triggered when a page has an <h1> heading exceeding 70 characters in length.

## H2 (5)

_Headings are titles and subtitles within the copy of a page to guide users and search engines to better understand the content. The h2 heading is often used to describe sections within a document and act as signposts for the user. Find issues related to missing, duplicate, long or non-sequential h2's._

- **[Missing](https://www.screamingfrog.co.uk/seo-spider/issues/h2/h2-missing/)** — Warning · Low — Pages which have a missing <h2> , the content is empty or has a whitespace. _Trigger:_ This issue is triggered when a page has a missing <h2> tag, the content is empty, or contains only whitespace.
- **[Multiple](https://www.screamingfrog.co.uk/seo-spider/issues/h2/h2-multiple/)** — Warning · Low — Pages which have multiple <h2> s. _Trigger:_ This issue is triggered when a page contains multiple <h2> tags.
- **[Non-sequential](https://www.screamingfrog.co.uk/seo-spider/issues/h2/h2-non-sequential/)** — Warning · Low — Pages with an <h2> that is not the second heading level after the <h1> on the page. _Trigger:_ This issue is triggered when a page’s <h2> is not the second heading level following the <h1> on the page.
- **[Duplicate](https://www.screamingfrog.co.uk/seo-spider/issues/h2/h2-duplicate/)** — Opportunity · Low — Pages which have duplicate <h2> s. _Trigger:_ This issue is triggered when pages have duplicate <h2> tags.
- **[Over 70 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/h2/h2-over-70-characters/)** — Opportunity · Low — Pages which have <h2> s over 70 characters in length. _Trigger:_ This issue is triggered when a page has an <h2> heading exceeding 70 characters in length.

## Content (11)

_Ensuring your web pages deliver the best on-page content is vital to satisfy users and for SEO. Find issues related to exact and near duplicate content, low content, spelling, grammar and readability._

- **[Exact Duplicates](https://www.screamingfrog.co.uk/seo-spider/issues/content/exact-duplicates/)** — Issue · High — Pages that are identical to each other using the MD5 algorithm which calculates a ‘hash’ value for each page and can be seen in the ‘hash’ column. _Trigger:_ This issue is triggered when pages are identical to each other.
- **[Spelling Errors](https://www.screamingfrog.co.uk/seo-spider/issues/content/spelling-errors/)** — Issue · Medium — Pages which contain spelling errors. Spelling, punctuation and grammar issues are a poor experience for users. _Trigger:_ This issue is triggered when pages contain spelling errors.
- **[Grammar Errors](https://www.screamingfrog.co.uk/seo-spider/issues/content/grammar-errors/)** — Issue · Medium — Pages which contain grammar errors. Grammar, punctuation and spelling issues are a poor experience for users. _Trigger:_ This issue is triggered when pages contain grammar errors.
- **[Soft 404 Pages](https://www.screamingfrog.co.uk/seo-spider/issues/content/soft-404-pages/)** — Warning · High — Pages that respond with a ‘200’ status code suggesting they are ‘OK’, but appear to be an error page – often referred to as a ‘404’ or ‘page not found’. _Trigger:_ This issue is triggered when pages respond with a ‘200 OK’ status code but appear to be error pages, typically resembling a ‘404 Page Not Found’ error.
- **[Lorem Ipsum Placeholder](https://www.screamingfrog.co.uk/seo-spider/issues/content/lorem-ipsum-placeholder/)** — Warning · High — Pages that contain ‘Lorem ipsum’ text that is commonly used as a placeholder to demonstrate the visual form of a webpage. _Trigger:_ This issue is triggered when pages contain the words ‘Lorem ipsum dolor’.
- **[Near Duplicates](https://www.screamingfrog.co.uk/seo-spider/issues/content/near-duplicates/)** — Warning · Medium — Pages that are near duplicate in content based upon the configured similarity threshold (set at 90% by default) using the minhash algorithm. _Trigger:_ This issue is triggered when pages are near duplicates in content, based on a configured similarity threshold (defaulted to 90%).
- **[Semantically Similar](https://www.screamingfrog.co.uk/seo-spider/issues/content/semantically-similar/)** — Warning · Medium — Pages that are semantically similar in content based upon the configured cosine semantic similarity threshold. High semantic similarity can be completely normal, but it can also indicate duplicate or overlapping content that should be reviewed. _Trigger:_ This issue is triggered when pages are semantically similar in content, based on a configured cosine similarity threshold (defaulted to 0.95).
- **[Low Relevance Content](https://www.screamingfrog.co.uk/seo-spider/issues/content/low-relevance-content/)** — Warning · Low — Pages that are potentially less relevant or off-topic compared to the overall content theme of the website based upon the configured low relevance threshold. _Trigger:_ This issue is triggered when pages are semantically low in relevance compared to the main content theme of the website based upon the configured low relevance threshold (defauted to 0.4).
- **[Low Content Pages](https://www.screamingfrog.co.uk/seo-spider/issues/content/low-content-pages/)** — Opportunity · Medium — Pages with a word count that is below the default 200 words. _Trigger:_ This issue is triggered when pages have a word count below the default threshold of 200 words.
- **[Readability Difficult](https://www.screamingfrog.co.uk/seo-spider/issues/content/readability-difficult/)** — Opportunity · Low — Copy on the page is difficult to read and best understood by college graduates according to the Flesch reading-ease score formula. _Trigger:_ This issue is triggered when the copy on a page is difficult to read, as indicated by a low Flesch reading-ease score, suggesting it’s best understood by college graduates.
- **[Readability Very Difficult](https://www.screamingfrog.co.uk/seo-spider/issues/content/readability-very-difficult/)** — Opportunity · Low — Copy on the page is very difficult to read and best understood by university graduates according to the Flesch reading-ease score formula. _Trigger:_ This issue is triggered when the copy on a page is difficult to read, as indicated by a low Flesch reading-ease score, suggesting it’s best understood by University graduates.

## Images (7)

_Imagery is crucial in delivering rich web experiences, whether that's to support branding, selling products or impactful visuals. Find issues related to large images, missing alt text, incorrectly sized images and cumulative layout shift._

- **[Missing Alt Text](https://www.screamingfrog.co.uk/seo-spider/issues/images/missing-alt-text/)** — Issue · Low — Images that have an alt attribute, but are missing alt text. _Trigger:_ This issue is triggered when images on a page have an alt attribute but are missing the alt text.
- **[Missing Alt Attribute](https://www.screamingfrog.co.uk/seo-spider/issues/images/missing-alt-attribute/)** — Issue · Low — Images that are missing an alt attribute all together. _Trigger:_ Images that are missing an alt attribute all together.
- **[Background Images](https://www.screamingfrog.co.uk/seo-spider/issues/images/background-images/)** — Warning · Low — CSS background and dynamically loaded images discovered across the website, which should be used for non-critical and decorative purposes. _Trigger:_ This issue is triggered when CSS background images and dynamically loaded images are used extensively across a website.
- **[Over 100 kb](https://www.screamingfrog.co.uk/seo-spider/issues/images/over-100-kb/)** — Opportunity · Medium — Large images over 100kb in size. _Trigger:_ This issue is triggered when a page contains large images over 100kb in size.
- **[Alt Text Over 100 Characters](https://www.screamingfrog.co.uk/seo-spider/issues/images/alt-text-over-100-characters/)** — Opportunity · Low — Images which have one instance of alt text over 100 characters in length. This is not strictly an issue, however image alt text should be concise and descriptive. _Trigger:_ This issue is triggered when an image on a page has alt text exceeding 100 characters in length.
- **[Incorrectly Sized Images](https://www.screamingfrog.co.uk/seo-spider/issues/images/incorrectly-sized-images/)** — Opportunity · Low — Images identified where their real dimensions (WxH) do not match the display dimensions when rendered. _Trigger:_ This issue is triggered when the actual dimensions of images do not match their display dimensions on the page, and there’s an estimated file size difference of 4kb or more.
- **[Missing Size Attributes](https://www.screamingfrog.co.uk/seo-spider/issues/images/missing-size-attributes/)** — Opportunity · Low — Image elements without dimensions (width and height size attributes) specified in the HTML. _Trigger:_ This issue is triggered when image elements on a page lack specified dimensions (width and height size attributes) in the HTML.

## Canonicals (10)

_Rel="canonical" can be used to help reduce duplicate content, and provide a hint to the search engines about which version of a URL should be indexed in the search results. Find issues related to pages missing canonicals, canonicalised pages, non-indexable canonicals and more._

- **[Multiple Conflicting](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/multiple-conflicting/)** — Issue · High — Pages with multiple canonicals set for a URL that have different URLs specified (via either multiple link elements, HTTP header, or both combined). _Trigger:_ This issue is triggered when pages have multiple canonicals set with different URLs, which can be through multiple link elements, an HTTP header, or a combination of both.
- **[Non-Indexable Canonical](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/non-indexable-canonical/)** — Issue · High — Pages with a canonical URL specified that is non-indexable. _Trigger:_ This issue is triggered when pages have a canonical URL pointing to a non-indexable location.
- **[Invalid Attribute In Annotation](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/invalid-attribute-in-annotation/)** — Issue · High — Pages with a rel=”canonical” annotation that includes an alternate version using an hreflang, lang, media, or type attribute. _Trigger:_ This issue is triggered when URLs include rel=”canonical” annotations with hreflang, lang, media, and type attributes.
- **[Contains Fragment URL](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/contains-fragment-url/)** — Issue · High — Pages with a rel=”canonical” that includes a fragment URL in the href attribute. _Trigger:_ This issue is triggered when URLs include rel=”canonical” annotations with an href that contains a URL with a fragment in it.
- **[Outside <head>](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/canonicals-outside-head/)** — Issue · High — Pages with a canonical link element that is outside of the <head> element in the HTML. _Trigger:_ This issue is triggered when a page has a canonical link element placed outside of the <head> element in the HTML.
- **[Canonicalised](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/canonicalised/)** — Warning · High — Pages that have a canonical to a different URL. The URL is ‘canonicalised’ to another location. _Trigger:_ This issue is triggered when pages have a canonical link pointing to a different URL.
- **[Missing](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/canonical-missing/)** — Warning · Medium — Pages that have no canonical URL present either as a link element, or via HTTP header. _Trigger:_ This issue is triggered when pages lack a canonical URL, neither specified in a link element nor via an HTTP header.
- **[Unlinked](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/unlinked/)** — Warning · Medium — URLs that are only discoverable via rel=”canonical” and are not linked to via hyperlinks on the website. _Trigger:_ This issue is triggered when URLs are only discoverable via rel=”canonical” tags and are not linked to via hyperlinks on the website.
- **[Multiple](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/canonical-multiple/)** — Warning · Low — Pages with multiple canonicals set for a URL (either multiple link elements, HTTP header, or both combined). _Trigger:_ This issue is triggered when pages have multiple canonical tags set for a URL, which can occur through multiple link elements, HTTP headers, or a combination of both.
- **[Canonical Is Relative](https://www.screamingfrog.co.uk/seo-spider/issues/canonicals/canonical-is-relative/)** — Warning · Low — Pages that have a relative rather than absolute rel=”canonical” link tag. _Trigger:_ This issue is triggered when pages use a relative rather than an absolute URL in the rel=”canonical” link tag.

## Pagination (7)

_Pagination is a common way to divide and display a subset of results to users for improved page performance or UX. Find issues related to pagination setup, including non-200 response URLs in pagination attributes, non-indexable paginated pages and sequence problems._

- **[Pagination URL Not In Anchor Tag](https://www.screamingfrog.co.uk/seo-spider/issues/pagination/pagination-url-not-in-anchor-tag/)** — Issue · High — URLs contained in either, or both, the rel=”next” and rel=”prev” attributes of the page, are not found as a hyperlink in an HTML anchor element on the page itself. _Trigger:_ This issue is triggered when URLs specified in the rel=”next” and rel=”prev” attributes are not found as hyperlinks in an HTML anchor element on the page itself.
- **[Non-200 Pagination URLs](https://www.screamingfrog.co.uk/seo-spider/issues/pagination/non-200-pagination-urls/)** — Issue · High — URLs contained in the rel=”next” and rel=”prev” attributes do not respond with a 200 ‘OK’ status code. _Trigger:_ This issue is triggered when URLs in the rel=”next” and rel=”prev” attributes do not respond with a 200 ‘OK’ status code.
- **[Unlinked Pagination URLs](https://www.screamingfrog.co.uk/seo-spider/issues/pagination/unlinked-pagination-urls/)** — Issue · Medium — URLs contained in the rel=”next” and rel=”next” attributes are not linked to across the website. _Trigger:_ This issue is triggered when URLs in the rel=”next” and rel=”next” attributes are not linked elsewhere on the website.
- **[Multiple Pagination URLs](https://www.screamingfrog.co.uk/seo-spider/issues/pagination/multiple-pagination-urls/)** — Issue · Low — There are multiple rel=”next” and rel=”next” attributes on the page (when there shouldn’t be more than a single rel=”next” or rel=”next” attribute). _Trigger:_ This issue is triggered when a page contains multiple rel=”next” and rel=”next” attributes.
- **[Pagination Loop](https://www.screamingfrog.co.uk/seo-spider/issues/pagination/pagination-loop/)** — Issue · Low — URLs that have rel=”next” and rel=”next” attributes that loop back to a previously encountered URL. _Trigger:_ This issue is triggered when URLs with rel=”next” and rel=”next” attributes loop back to a previously encountered URL.
- **[Sequence Error](https://www.screamingfrog.co.uk/seo-spider/issues/pagination/sequence-error/)** — Issue · Low — URLs that have an error in the rel=”next” and rel=”prev” HTML link elements sequence. _Trigger:_ This issue is triggered when there is an error in the sequence of rel=”next” and rel=”prev” HTML link elements, indicating a breakdown in their reciprocal relationship.
- **[Non-Indexable](https://www.screamingfrog.co.uk/seo-spider/issues/pagination/non-indexable/)** — Warning · High — The paginated URL is non-indexable. _Trigger:_ This issue is triggered when paginated URLs are non-indexable.

## Directives (10)

_Robots directives using either the robots meta tag or X-Robots-Tag HTTP Header give search engine crawlers instructions about how to crawl and index web pages. Find issues related to noindex, nofollow and none directives._

- **[Outside <head>](https://www.screamingfrog.co.uk/seo-spider/issues/directives/directive-outside-head/)** — Issue · High — Pages with a meta robots that is outside of the <head> element in the HTML. _Trigger:_ This issue is triggered when pages have a meta robots tag placed outside of the <head> element in the HTML.
- **[NoImageIndex](https://www.screamingfrog.co.uk/seo-spider/issues/directives/noimageindex/)** — Issue · Low — URLs containing a ‘noimageindex’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘noimageindex’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[Noindex](https://www.screamingfrog.co.uk/seo-spider/issues/directives/noindex/)** — Warning · High — URLs containing a ‘noindex’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘noindex’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[Nofollow](https://www.screamingfrog.co.uk/seo-spider/issues/directives/nofollow/)** — Warning · High — URLs containing a ‘nofollow’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘nofollow’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[None](https://www.screamingfrog.co.uk/seo-spider/issues/directives/none/)** — Warning · High — URLs containing a ‘none’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘none’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[Unavailable_After](https://www.screamingfrog.co.uk/seo-spider/issues/directives/unavailable-after/)** — Warning · Medium — URLs containing a ‘unavailable_after’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘unavailable_after’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[NoSnippet](https://www.screamingfrog.co.uk/seo-spider/issues/directives/nosnippet/)** — Warning · Low — URLs containing a ‘nosnippet’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘nosnippet’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[NoODP](https://www.screamingfrog.co.uk/seo-spider/issues/directives/noodp/)** — Warning · Low — URLs containing a ‘noodp’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘noodp’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[NoYDIR](https://www.screamingfrog.co.uk/seo-spider/issues/directives/noydir/)** — Warning · Low — URLs containing a ‘noydir’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘noydir’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.
- **[NoTranslate](https://www.screamingfrog.co.uk/seo-spider/issues/directives/notranslate/)** — Warning · Low — URLs containing a ‘notranslate’ directive in either a robots meta tag or X-Robots-Tag in the HTTP header. _Trigger:_ This issue is triggered when URLs contain a ‘notranslate’ directive, either in a robots meta tag within the HTML or in an X-Robots-Tag in the HTTP header.

## Hreflang (12)

_Hreflang lets search engines know about multiple versions of a page for different languages and regions, to enable them to return the appropriate version to users under search. Find issues related to non-200 hreflang URLs, missing return links and incorrect language or region codes._

- **[Non-200 Hreflang URLs](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/non-200-hreflang-urls/)** — Issue · High — URLs contained within rel=”alternate” hreflang annotations that do not have a 200 response code, such as URLs blocked by robots.txt, no responses, 3XX (redirects), 4XX (client errors) or 5XX (server errors). _Trigger:_ This issue is triggered when URLs included in rel=”alternate” hreflang annotations do not respond with a 200 status code.
- **[Missing Return Links](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/missing-return-links/)** — Issue · High — URLs with missing return links (or ‘return tags’ in Google Search Console) to them, from their alternate pages. _Trigger:_ This issue is triggered when URLs with hreflang annotations lack corresponding return links from their alternate versions.
- **[Inconsistent Language & Region Confirmation Links](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/inconsistent-language-region-confirmation-links/)** — Issue · High — URLs with inconsistent language and regional return links to them. This is where a return link has a different language or regional value than the URL is referencing itself. _Trigger:_ This issue is triggered when URLs have hreflang annotations with inconsistent language or regional return links.
- **[Non-Canonical Return Links](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/non-canonical-return-links/)** — Issue · High — URLs with non-canonical hreflang return links. _Trigger:_ This issue is triggered when hreflang return links point to non-canonical versions of URLs.
- **[Noindex Returns Links](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/noindex-returns-links/)** — Issue · High — URLs with return links which have a ‘noindex’ meta tag. _Trigger:_ This issue is triggered when hreflang return links point to pages with a ‘noindex’ meta tag.
- **[Incorrect Language & Region Codes](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/incorrect-language-region-codes/)** — Issue · High — URLs with hreflang annotations that contain invalid language (in ISO 639-1 format) and or optional regional (in ISO 3166-1 Alpha 2 format) values. _Trigger:_ This issue is triggered when hreflang annotations contain invalid language codes (based on ISO 639-1 format) or optional regional codes (based on ISO 3166-1 Alpha 2 format).
- **[Multiple Entries](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/multiple-entries/)** — Issue · High — URLs with multiple entries to a language or regional code. _Trigger:_ This issue is triggered when URLs have multiple entries for the same language or regional code in their hreflang annotations.
- **[Not Using Canonical](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/not-using-canonical/)** — Issue · High — URLs not using the canonical URL on the page in its own hreflang annotation. Hreflang should only include canonical versions of URLs. _Trigger:_ This issue arises when hreflang annotations on a page do not reference the page’s own canonical URL.
- **[Outside <head>](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/hreflang-outside-head/)** — Issue · High — Pages with an hreflang link element that is outside of the <head> element in the HTML. _Trigger:_ This issue occurs when pages feature an hreflang link element located outside of the <head> element in the HTML.
- **[Unlinked Hreflang URLs](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/unlinked-hreflang-urls/)** — Issue · Medium — URLs that are only discoverable via rel=”alternate” hreflang link annotations. _Trigger:_ This issue is triggered when URLs are only discoverable via rel=”alternate” hreflang link annotations and are not linked through traditional anchor tags elsewhere on the website.
- **[Missing Self Reference](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/missing-self-reference/)** — Warning · Low — URLs missing their own self referencing rel=”alternate” hreflang annotation. _Trigger:_ This issue is triggered when URLs lack their own self-referencing rel=”alternate” hreflang annotation.
- **[Missing X-Default](https://www.screamingfrog.co.uk/seo-spider/issues/hreflang/missing-x-default/)** — Warning · Low — URLs missing an x-default hreflang attribute. This is optional, and not necessarily an issue. _Trigger:_ This issue is identified when URLs lack an x-default hreflang attribute.

## JavaScript (16)

_Search engines today are typically able to render web pages to crawl and index pages that use JavaScript. However, JavaScript-rich websites that rely on client-side rendering can be more fragile. Find issues related to blocked resources, identifying JS content, links and key elements._

- **[Noindex Only in Original HTML](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/noindex-only-in-original-html/)** — Issue · High — Pages that contain a noindex in the raw HTML, and not in the rendered HTML. _Trigger:_ This issue is triggered when pages have a meta robots ‘noindex’ directive in the raw HTML, which is then removed or not present in the rendered HTML after JavaScript execution.
- **[Nofollow Only in Original HTML](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/nofollow-only-in-original-html/)** — Issue · High — Pages that contain a meta robots nofollow in the raw HTML, and not in the rendered HTML. _Trigger:_ Pages that contain a meta robots ‘nofollow’ directive in the raw HTML, and not in the rendered HTML.
- **[Canonical Mismatch](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/canonical-mismatch/)** — Issue · High — Pages that contain a different canonical link in the raw HTML to the rendered HTML after JavaScript execution. _Trigger:_ This issue is triggered when pages have different canonical links in the raw HTML compared to the rendered HTML after JavaScript execution.
- **[Uses Old AJAX Crawling Scheme URLs](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/uses-old-ajax-crawling-scheme-urls/)** — Issue · Medium — URLs that are still using the Old AJAX crawling scheme (a URL containing a #! hash fragment) which was officially deprecated as of October 2015. _Trigger:_ This issue is triggered when URLs are still using the old AJAX crawling scheme, characterised by a URL containing a #! hash fragment (also known as “hashbangs”).
- **[Uses Old AJAX Crawling Scheme Meta Fragment Tag](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/uses-old-ajax-crawling-scheme-meta-fragment-tag/)** — Issue · Medium — URLs include a meta fragment tag that indicates the page is still using the Old AJAX crawling scheme which was officially deprecated as of October 2015. _Trigger:_ This issue is triggered when URLs include a meta fragment tag indicating that the page is still using the Old AJAX crawling scheme, which was officially deprecated as of October 2015.
- **[Pages with Blocked Resources](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/pages-with-blocked-resources/)** — Warning · High — Pages with resources (such as images, JavaScript and CSS) that are blocked from rendering by robots.txt or an error. _Trigger:_ This issue is triggered when pages have resources such as images, JavaScript, and CSS that are blocked from rendering due to restrictions in the robots.txt file or because of an error.
- **[Contains JavaScript Links](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/contains-javascript-links/)** — Warning · Medium — Pages that contain hyperlinks that are only discovered in the rendered HTML after JavaScript execution. _Trigger:_ This issue is triggered when pages contain hyperlinks that are only discoverable in the rendered HTML following JavaScript execution, and are not present in the raw HTML.
- **[Contains JavaScript Content](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/contains-javascript-content/)** — Warning · Medium — Pages that contain body text that’s only discovered in the rendered HTML after JavaScript execution. _Trigger:_ This issue is triggered when pages contain body text that only becomes visible in the rendered HTML after JavaScript execution, and is not present in the raw HTML.
- **[Page Title Only in Rendered HTML](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/page-title-only-in-rendered-html/)** — Warning · Medium — Pages that contain a page title only in the rendered HTML after JavaScript execution. _Trigger:_ This issue is triggered when pages contain a page title only in the rendered HTML after JavaScript execution, with no page title present in the raw HTML.
- **[Page Title Updated by JavaScript](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/page-title-updated-by-javascript/)** — Warning · Medium — Pages that have page titles that are modified by JavaScript. _Trigger:_ This issue is triggered when the page title present in the raw HTML of a webpage is modified by JavaScript, resulting in a different title in the rendered HTML.
- **[Meta Description Only in Rendered HTML](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/meta-description-only-in-rendered-html/)** — Warning · Medium — Pages that contain a meta description only in the rendered HTML after JavaScript execution. _Trigger:_ This issue is triggered when pages include a meta description only in the rendered HTML after JavaScript execution, with no meta description present in the raw HTML.
- **[Meta Description Updated by JavaScript](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/meta-description-updated-by-javascript/)** — Warning · Medium — Pages that have meta descriptions that are modified by JavaScript. _Trigger:_ This issue is triggered when the meta description in the raw HTML of a webpage is modified by JavaScript, resulting in a different meta description in the rendered HTML.
- **[H1 Only in Rendered HTML](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/h1-only-in-rendered-html/)** — Warning · Medium — Pages that contain an h1 only in the rendered HTML after JavaScript execution. _Trigger:_ This issue is triggered when pages contain an <h1> (heading 1) element only in the rendered HTML following JavaScript execution, with no <h1> element present in the raw HTML.
- **[H1 Updated by JavaScript](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/h1-updated-by-javascript/)** — Warning · Medium — Pages that have h1s that are modified by JavaScript. _Trigger:_ This issue is triggered when the <h1> element present in the raw HTML of a webpage is modified by JavaScript, resulting in a different <h1> in the rendered HTML.
- **[Canonical Only in Rendered HTML](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/canonical-only-in-rendered-html/)** — Warning · Low — Pages that contain a canonical only in the rendered HTML after JavaScript execution. _Trigger:_ This issue is triggered when pages only contain a canonical link in the raw HTML after JavaScript execution.
- **[Pages With JavaScript Errors](https://www.screamingfrog.co.uk/seo-spider/issues/javascript/pages-with-javascript-errors/)** — Warning · Low — Pages with JavaScript errors captured in the Chrome DevTools console log during page rendering. _Trigger:_ This issue is triggered when pages have JavaScript errors that are captured in the Chrome DevTools console log during page rendering.

## Links (12)

_Links are used by website users to navigate pages, and by search engines to understand a website and score them. Find link issues related to pages with high crawl depth, without internal outlinks, non-descriptive anchor text and more._

- **[Outlinks To Localhost](https://www.screamingfrog.co.uk/seo-spider/issues/links/outlinks-to-localhost/)** — Issue · High — Pages that contain links that reference localhost or the 127.0.0.1 loopback address. _Trigger:_ This issue is triggered when pages contain links that reference localhost or the 127.0.0.1 loopback address.
- **[Pages With Uncrawlable Internal Outlinks](https://www.screamingfrog.co.uk/seo-spider/issues/links/pages-with-uncrawlable-internal-outlinks/)** — Warning · High — Pages that contain internal links that are not in an <a> tag with an href attribute. _Trigger:_ This issue is triggered when pages have an internal outlink that is an uncrawlable link type.
- **[Pages Without Internal Outlinks](https://www.screamingfrog.co.uk/seo-spider/issues/links/pages-without-internal-outlinks/)** — Warning · High — Pages that do not contain links to other internal pages. _Trigger:_ This issue is triggered when pages lack links to other internal pages.
- **[Non-Indexable Page Inlinks Only](https://www.screamingfrog.co.uk/seo-spider/issues/links/non-indexable-page-inlinks-only/)** — Warning · High — Indexable pages that are only linked to from pages that are non-indexable, which includes noindex, canonicalised or robots.txt disallowed pages. _Trigger:_ This issue is triggered when indexable pages are only linked to from pages that are non-indexable, including those marked with noindex, those that have been canonicalised to other pages, or pages disallowed by robots.txt.
- **[Internal Nofollow Outlinks](https://www.screamingfrog.co.uk/seo-spider/issues/links/internal-nofollow-outlinks/)** — Warning · Low — Pages that use rel=”nofollow” on internal outlinks. Links with nofollow link attributes will typically not be followed by search engines. _Trigger:_ This issue is triggered when pages use the rel=”nofollow” attribute on internal outlinks.
- **[Pages With High External Outlinks](https://www.screamingfrog.co.uk/seo-spider/issues/links/pages-with-high-external-outlinks/)** — Warning · Low — Pages that have a high number of followed external outlinks on them based upon the ‘High External Outlinks’ preferences under ‘Config > Spider > Preferences’. _Trigger:_ This issue is triggered when pages have a high number of followed external outlinks, as defined by the ‘High External Outlinks’ setting in ‘Config > Spider > Preferences’ in the SEO Spider.
- **[Pages With High Internal Outlinks](https://www.screamingfrog.co.uk/seo-spider/issues/links/pages-with-high-internal-outlinks/)** — Warning · Low — Pages that have a high number of followed internal outlinks on them based upon the ‘High Internal Outlinks’ preferences under ‘Config > Spider > Preferences’. _Trigger:_ This issue is triggered when pages have a high number of followed internal outlinks, as defined by the ‘High Internal Outlinks’ setting in ‘Config > Spider > Preferences’ in the SEO Spider.
- **[Follow & Nofollow Internal Inlinks To Page](https://www.screamingfrog.co.uk/seo-spider/issues/links/follow-nofollow-internal-inlinks-to-page/)** — Warning · Low — Pages that have both rel=”nofollow” and follow links to them from other pages. _Trigger:_ This issue is triggered when pages have a mix of links marked with rel=”nofollow” and others without this attribute pointing to them from other pages.
- **[Internal Nofollow Inlinks Only](https://www.screamingfrog.co.uk/seo-spider/issues/links/internal-nofollow-inlinks-only/)** — Warning · Low — Pages that only have rel=”nofollow” links to them from other pages. _Trigger:_ This issue is triggered when pages only have links marked with rel=”nofollow” pointing to them from other pages within the website.
- **[Pages With High Crawl Depth](https://www.screamingfrog.co.uk/seo-spider/issues/links/pages-with-high-crawl-depth/)** — Opportunity · Medium — Pages that have a high crawl depth from the start page of the crawl based upon the ‘Crawl Depth’ preferences which are set at 4 or above. _Trigger:_ This issue is triggered when pages have a high crawl depth from the start page of the crawl, typically set at a depth of 4 or above.
- **[Internal Outlinks With No Anchor Text](https://www.screamingfrog.co.uk/seo-spider/issues/links/internal-outlinks-with-no-anchor-text/)** — Opportunity · Low — Pages that have internal links without anchor text, or images that are hyperlinked without alt text. _Trigger:_ This issue is triggered when pages have internal links without anchor text or images that are hyperlinked, but lack alt text.
- **[Non-Descriptive Anchor Text In Internal Outlinks](https://www.screamingfrog.co.uk/seo-spider/issues/links/non-descriptive-anchor-text-in-internal-outlinks/)** — Opportunity · Low — Pages that have internal outlinks with anchor text that is not descriptive, such as ‘click here’ or ‘learn more’ based upon the preferences under ‘Config > Spider > Preferences’. _Trigger:_ This issue is triggered when pages have internal outlinks with anchor text that is not descriptive, such as generic phrases like “click here” or “learn more”.

## AMP (16)

_AMP is an open-source HTML framework that was created to help produce fast-loading pages optimised for mobile. There are specific requirements for AMP and the setup. Find issues related to the SEO setup, as well as AMP specifications using the official AMP validator._

- **[Non-200 Response](https://www.screamingfrog.co.uk/seo-spider/issues/amp/non-200-response/)** — Issue · High — AMP URLs which do not respond with a 200 ‘OK’ status code. _Trigger:_ This issue is triggered when AMP URLs do not respond with a 200 ‘OK’ status code.
- **[Missing Non-AMP Return Link](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-non-amp-return-link/)** — Issue · High — AMP URLs that have a canonical non-AMP version that does not contain a rel=”amphtml” URL back to the AMP URL. _Trigger:_ This issue is triggered when AMP URLs are associated with a canonical non-AMP version that lacks a rel=”amphtml” link pointing back to the AMP URL.
- **[Missing Canonical to Non-AMP](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-canonical-to-non-amp/)** — Issue · High — AMP URLs with a canonical that does not go to a non-AMP version, but to another AMP URL. _Trigger:_ This issue is triggered when AMP URLs have a canonical tag that points to another AMP URL instead of the corresponding non-AMP version.
- **[Non-Indexable Canonical](https://www.screamingfrog.co.uk/seo-spider/issues/amp/amp-non-indexable-canonical/)** — Issue · High — The AMP canonical URL is a non-indexable page. _Trigger:_ This issue is triggered when the canonical URL set for an AMP page points to a non-indexable version of the non-AMP equivalent.
- **[Missing <html amp> Tag](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-htmlamp-tag/)** — Issue · High — AMP HTML documents must contain a top-level HTML or HTML AMP tag. _Trigger:_ This issue is triggered when AMP HTML documents do not contain a top-level HTML or HTML AMP tag.
- **[Missing/Invalid Doctype HTML Tag](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-invalid-doctype-html-tag/)** — Issue · High — AMP HTML documents must start with the doctype, doctype HTML. _Trigger:_ This issue is triggered when AMP HTML documents do not start with the correct doctype declaration.
- **[Missing Head Tag](https://www.screamingfrog.co.uk/seo-spider/issues/amp/amp-missing-head-tag/)** — Issue · High — AMP HTML documents must contain head tags (they are optional in HTML). _Trigger:_ This issue is triggered when AMP HTML documents do not start with the correct doctype declaration.
- **[Missing Body Tag](https://www.screamingfrog.co.uk/seo-spider/issues/amp/amp-missing-body-tag/)** — Issue · High — AMP HTML documents must contain body tags (they are optional in HTML). _Trigger:_ This issue is triggered when AMP HTML documents do not contain body tags.
- **[Missing Canonical](https://www.screamingfrog.co.uk/seo-spider/issues/amp/amp-missing-canonical/)** — Issue · High — AMP URLs must contain a canonical tag inside their head that points to the regular HTML version of the AMP HTML document, or to itself if no such HTML version exists. _Trigger:_ This issue is triggered when AMP URLs do not contain a proper canonical tag inside their head that points to the regular HTML version of the AMP HTML document, or to the AMP document itself if no corresponding HTML version exists.
- **[Missing/Invalid Meta Charset Tag](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-invalid-meta-charset-tag/)** — Issue · High — AMP HTML documents must contain a <meta charset=”UTF-8″> tag as the first child of their head tag. _Trigger:_ This issue is triggered when AMP HTML documents do not contain a <meta charset=”UTF-8″> tag as the first child of their head tag.
- **[Missing/Invalid Meta Viewport Tag](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-invalid-meta-viewport-tag/)** — Issue · High — AMP HTML documents must contain a: _Trigger:_ This issue is triggered when AMP HTML documents do not contain a: <meta name="viewport" content=”width=device-width,minimum-scale=1″> Tag within their head tag.
- **[Missing/Invalid AMP Script](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-invalid-amp-script/)** — Issue · High — AMP HTML documents must contain a: _Trigger:_ This issue is triggered when AMP HTML documents do not contain the required script tag: <script async src="https://cdn.ampproject.org/v0/amp-script-0.1.js"></script> Inside their head tag.
- **[Missing/Invalid AMP Boilerplate](https://www.screamingfrog.co.uk/seo-spider/issues/amp/missing-invalid-amp-boilerplate/)** — Issue · High — AMP HTML documents must contain the AMP boilerplate code in their head tag. _Trigger:_ This issue is triggered when AMP HTML documents do not contain the AMP boilerplate code in their head.
- **[Contains Disallowed HTML](https://www.screamingfrog.co.uk/seo-spider/issues/amp/contains-disallowed-html/)** — Issue · High — AMP URLs with disallowed HTML for AMP according to the official AMP validator ( https://validator.ampproject.org/ ). _Trigger:_ This issue is triggered when AMP URLs contain HTML that is disallowed according to the official AMP validator.
- **[Other Validation Errors](https://www.screamingfrog.co.uk/seo-spider/issues/amp/other-validation-errors/)** — Issue · High — AMP URLs with validation errors for AMP using the official AMP validator ( https://validator.ampproject.org/ ). _Trigger:_ This issue is triggered when AMP URLs have validation errors as identified by the official AMP validator.
- **[Indexable](https://www.screamingfrog.co.uk/seo-spider/issues/amp/indexable/)** — Warning · High — The AMP URL is indexable. AMP URLs with a non-AMP equivalent should be non-indexable (as they should have a canonical to the non-AMP equivalent). _Trigger:_ This issue is triggered when AMP URLs that have a corresponding non-AMP equivalent are set to be indexable.

## Structured Data (6)

_Structured data provides search engines with explicit clues about the meaning of pages and their components and can enable special search result features and enhancements in Google. Find issues related to Schema.org specifications and Google’s rich result feature requirements._

- **[Validation Errors](https://www.screamingfrog.co.uk/seo-spider/issues/structured-data/validation-errors/)** — Issue · High — URLs that contain structured data validation errors related to Schema.org. _Trigger:_ This issue is triggered when URLs contain validation errors in their structured data for Schema.org.
- **[Rich Result Validation Errors](https://www.screamingfrog.co.uk/seo-spider/issues/structured-data/rich-result-validation-errors/)** — Issue · High — URLs that contain Google rich result feature validation errors. Google rich result feature validation will show errors for missing required properties or problems with the implementation of required properties. _Trigger:_ This issue is triggered when URLs contain missing required properties or problems with the implementation of required properties.
- **[Parse Errors](https://www.screamingfrog.co.uk/seo-spider/issues/structured-data/parse-errors/)** — Issue · High — URLs which have structured data that failed to parse correctly. _Trigger:_ This issue is triggered when URLs contain incorrect Schema.org markup that fails to parse.
- **[Missing](https://www.screamingfrog.co.uk/seo-spider/issues/structured-data/structured-data-missing/)** — Opportunity · Low — URLs that do not contain any structured data. _Trigger:_ This issue is triggered when URLs do not contain any structured data.
- **[Validation Warnings](https://www.screamingfrog.co.uk/seo-spider/issues/structured-data/validation-warnings/)** — Opportunity · Low — URLs that contain structured data validation warnings, such as for using older data-vocabulary.org schema rather than the recommended Schema.org. _Trigger:_ This issue is triggered when URLs contain older data-vocabulary.org schema rather than the recommended Schema.org.
- **[Rich Result Validation Warnings](https://www.screamingfrog.co.uk/seo-spider/issues/structured-data/rich-result-validation-warnings/)** — Opportunity · Low — URLs that contain Google rich result feature validation warnings. These will always be for ‘recommended properties’, rather than required properties. _Trigger:_ This issue is triggered when URLs contain validation warnings for Google rich result features due to missing or incorrectly implemented ‘recommended properties’.

## Sitemaps (6)

_XML Sitemaps should be up to date, error free, and include indexable, canonical versions of URLs to help search engines crawl and index the URLs that are important for a website. Find issues related to URLs not in the XML Sitemap, orphan URLs and non-indexable URLs._

- **[XML Sitemap With Over 50k URLs](https://www.screamingfrog.co.uk/seo-spider/issues/sitemaps/xml-sitemap-with-over-50k-urls/)** — Issue · High — XML Sitemaps that has more than the permitted 50k URLs. _Trigger:_ This issue is triggered when an XML Sitemap exceeds the permitted limit of 50,000 URLs.
- **[XML Sitemap Over 50mb](https://www.screamingfrog.co.uk/seo-spider/issues/sitemaps/xml-sitemap-over-50mb/)** — Issue · High — XML Sitemaps that is larger than the permitted 50mb file size. _Trigger:_ This issue is triggered when an XML Sitemap exceeds the permitted file size limit of 50MB when uncompressed.
- **[URLs Not In Sitemap](https://www.screamingfrog.co.uk/seo-spider/issues/sitemaps/urls-not-in-sitemap/)** — Issue · Medium — URLs that are not in an XML Sitemap, but were discovered in the crawl. _Trigger:_ This issue is triggered when there are URLs that were discovered during a website crawl but are not included in the site’s XML Sitemap.
- **[Orphan URLs](https://www.screamingfrog.co.uk/seo-spider/issues/sitemaps/orphan-urls/)** — Issue · Medium — URLs that are only in an XML Sitemap, but were not discovered during the crawl. _Trigger:_ This issue is triggered when URLs are found exclusively in an XML Sitemap but were not discovered during a website crawl via internal hyperlinks.
- **[Non-Indexable URLs In Sitemap](https://www.screamingfrog.co.uk/seo-spider/issues/sitemaps/non-indexable-urls-in-sitemap/)** — Issue · Medium — URLs that are in an XML Sitemap, but are non-indexable, and hence should be removed, or their indexability needs to be fixed. _Trigger:_ This issue is triggered when URLs listed in an XML Sitemap are non-indexable, meaning they have been configured (intentionally or unintentionally) in a way that prevents search engines from indexing them.
- **[URLs In Multiple Sitemaps](https://www.screamingfrog.co.uk/seo-spider/issues/sitemaps/urls-in-multiple-sitemaps/)** — Warning · Low — URLs that are in more than one XML Sitemap. _Trigger:_ This issue is triggered when URLs are listed in more than one XML Sitemap.

## PageSpeed (19)

_Page speed is a fundamental component of UX and by integrating the PageSpeed Insights API into a crawl, speed metrics, opportunities and diagnostics can be gathered at scale. Find issues related to render-blocking resources, large images, compression and more._

- **[Document Request Latency](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/document-request-latency/)** — Opportunity · Medium — Pages with resources that redirect, have a slow server response, or do not apply text compression. These can all contribute to latency and reducing page speed. _Trigger:_ This issue is triggered when – Pages contain resources that undergo redirection, causing an additional trip across the network and potentially delaying the loading of the resource by hundreds of milliseconds.
- **[LCP Request Discovery](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/lcp-request-discovery/)** — Opportunity · Medium — Pages with a Largest Contentful Paint (LCP) request discovery that can be optimised. _Trigger:_ This issue will trigger if a page fails on any of the below checks: Use fetchpriority=high on the image element, or on its preload directive.
- **[Render Blocking Requests](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/eliminate-render-blocking-resources/)** — Opportunity · Medium — Pages with resources that are blocking the first paint of the page. Lighthouse flags pages which have scripts that do not have defer or async attributes, and stylesheets without a disabled attribute, or media attribute that matches the device. _Trigger:_ This issue is triggered when pages contain resources that block the first paint of the page.
- **[Network Dependency Tree](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/network-dependency-tree/)** — Opportunity · Medium — Pages with a lot of latency on the critical path, caused by long chains and large resource download sizes. _Trigger:_ This insight only fails if a critical request is not discoverable early in the page.
- **[Use Efficient Cache Lifetimes](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/serve-static-assets-with-an-efficient-cache-policy/)** — Opportunity · Medium — Pages with resources that are not cached. HTTP caching can speed up your page load time on repeat visits. _Trigger:_ This issue is triggered when pages have resources that are not cached.
- **[Layout Shift Culprits](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/avoid-large-layout-shifts/)** — Opportunity · Medium — Pages that have layout shifts on DOM elements without any user interaction such as elements being added, removed, or their fonts changing as the page loads. _Trigger:_ This issue is triggered when certain DOM elements on a page contribute significantly to the Cumulative Layout Shift (CLS) metric.
- **[Improve Image Delivery](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/improve-image-delivery/)** — Opportunity · Medium — Pages where the download time of images can be reduced, improving the perceived load time of the page and Largest Contentful Paint (LCP). _Trigger:_ The insight will highlight images that have unnecessarily large download sizes.
- **[Forced Reflow](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/forced-reflow/)** — Opportunity · Medium — Pages with a forced reflow which can result in slowing down rendering and user interactions. _Trigger:_ This issue will trigger if a page fails on any of the below checks: Avoid, or at least reduce, the amount of DOM geometry writes that are done just before reads.
- **[Legacy JavaScript](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/avoid-serving-legacy-javascript-to-modern-browsers/)** — Opportunity · Medium — Pages with legacy JavaScript. Polyfills and transforms enable legacy browsers to use new JavaScript features. However, many aren’t necessary for modern browsers. _Trigger:_ This issue is triggered when pages include legacy JavaScript, such as polyfills and transforms, that are meant to enable legacy browsers to use new JavaScript features.
- **[Duplicated JavaScript](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/duplicated-javascript/)** — Opportunity · Medium — Pages with duplicate JavaScript libraries across different code bundles. Lighthouse detects duplicated code that would be quicker to load once. _Trigger:_ This issue will trigger if a page fails on any of the below checks: For pages with multiple JavaScript bundles, code splits large dependencies needed by multiple bundles to a common bundle.
- **[Avoid Enormous Network Payloads](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/avoid-enormous-network-payloads/)** — Opportunity · Medium — Pages with large network payloads that can reduce page speed. Large network payloads cost users real money and are highly correlated with long load times. _Trigger:_ Based on HTTP Archive data, the median network payload is between 1,700 and 1,900 KiB.
- **[Minify CSS](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/minify-css/)** — Opportunity · Medium — Pages with unminified CSS files that are larger than necessary in bytes and reducing page speed. _Trigger:_ This issue is triggered when pages include unminified CSS files, resulting in larger file sizes than necessary and subsequently reducing page speed.
- **[Minify JavaScript](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/minify-javascript/)** — Opportunity · Medium — Pages with unminified JavaScript files that are larger than necessary in bytes and reducing page speed. _Trigger:_ This issue is triggered when pages include unminified JavaScript files, leading to larger file sizes than necessary, which can subsequently reduce page speed.
- **[Reduce Unused CSS](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/remove-unused-css/)** — Opportunity · Medium — Pages with unused CSS that are larger than necessary in bytes and reducing page speed. _Trigger:_ This issue is triggered when pages include unused CSS, leading to file sizes that are larger than necessary and subsequently reducing page speed.
- **[Reduce Unused JavaScript](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/remove-unused-javascript/)** — Opportunity · Medium — Pages with unused JavaScript that are larger than necessary in bytes and reducing page speed. _Trigger:_ This issue is triggered when pages include unused JavaScript, resulting in larger file sizes than necessary, which can subsequently reduce page speed.
- **[Reduce JavaScript Execution Time](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/reduce-javascript-execution-time/)** — Opportunity · Medium — Pages with average or slow JavaScript execution time (over 2 seconds). When JavaScript takes a long time to execute, it slows down page performance. _Trigger:_ This issue is triggered when pages have an average or slow JavaScript execution time, exceeding 2 seconds.
- **[Minimize Main-Thread Work](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/minimize-main-thread-work/)** — Opportunity · Medium — Pages with average or slow execution timing on the main thread. The main thread of the renderer process typically handles most code that allows users to interact with a page. _Trigger:_ This issue is triggered when pages have average or slow execution timing on the main thread, particularly if the main thread is kept busy for longer than 4 seconds during load.
- **[Optimize DOM Size](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/avoid-excessive-dom-size/)** — Opportunity · Low — Pages with a large DOM size with a large layout or style recalculation exceeding a duration of 40ms. _Trigger:_ This issue is triggered when pages have a large layout or style recalculation exceeding a duration of 40ms.
- **[Font Display](https://www.screamingfrog.co.uk/seo-spider/issues/pagespeed/ensure-text-remains-visible-during-webfont-load/)** — Opportunity · Low — Pages with fonts that may flash or become invisible during page load, which can be annoying to users and reduce the visual appearance of page load speed. _Trigger:_ This issue is triggered when pages experience a “flash of unstyled text” (FOUT) or “flash of invisible text” (FOIT) with fonts during page load.

## Mobile (6)

_Websites must provide friendly and rich experience on mobile devices, as well as desktop. Test web pages using Lighthouse to identify mobile usability issues related to viewport, tap targets, content sizing and more._

- **[Viewport Not Set](https://www.screamingfrog.co.uk/seo-spider/issues/mobile/viewport-not-set/)** — Issue · High — Pages without a viewport meta tag, or a viewport meta tag without a content attribute that includes the text width= . _Trigger:_ This issue is triggered by Lighthouse when pages do not have a viewport meta tag, or the viewport meta tag is missing the content attribute that includes the text width= .
- **[Content Not Sized Correctly](https://www.screamingfrog.co.uk/seo-spider/issues/mobile/content-not-sized-correctly/)** — Issue · High — Pages with content that is smaller or larger than the viewport width, which means it may not render correctly on mobile devices. _Trigger:_ This issue is triggered by Lighthouse when pages width isn’t equal to the width of the viewport.
- **[Illegible Font Size](https://www.screamingfrog.co.uk/seo-spider/issues/mobile/illegible-font-size/)** — Issue · High — Pages with small font sizes that can make it difficult to read for users on mobile devices. _Trigger:_ This issue is triggered by Lighthouse when pages have a font size smaller than 12 px on more than 40% of the text.
- **[Contains Unsupported Plugins](https://www.screamingfrog.co.uk/seo-spider/issues/mobile/contains-unsupported-plugins/)** — Issue · High — Pages with browser plugins such as Flash, Silverlight, or Java Applets that most mobile devices and browsers do not support and search engines cannot index. _Trigger:_ This issue is triggered when pages have the following: Flash – Any <object> tags with a type attribute that matches application/x-shockwave-flash or any <embed> tags where the src attributed ends with .swf. .
- **[Target Size](https://www.screamingfrog.co.uk/seo-spider/issues/mobile/target-size/)** — Issue · Medium — Pages with tap targets that are too small or there is not enough space around them, which means they are difficult to interact with on mobile devices. _Trigger:_ This issue is triggered by the Axe accessibility testing library within Lighthouse when the following conditions are not met: Touch targets must be at least 24 by 24 CSS pixels in size.
- **[Mobile Alternate Link](https://www.screamingfrog.co.uk/seo-spider/issues/mobile/mobile-alternate-link/)** — Warning · High — Pages that contain a rel=”alternate” link element to a mobile version. _Trigger:_ This issue is triggered when pages have a rel=”alternate” link element with a ‘media’ attribute suggesting the website has separate mobile URLs.

## Accessibility (92)

_Improve site accessibility to make them more inclusive and user friendly for people with disabilities. Automate finding accessibility issues using the inbuilt open-source AXE accessibility engine that powers Lighthouse._

- **[Best Practice – Accesskey Attribute Value Must Be Unique](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-accesskey-attribute-value-must-be-unique/)** — Warning · High — All accesskey attribute values in a document must be unique. Accesskeys must not be repeated to prevent unexpected effects for keyboard users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Elements Must Not Have Tabindex Greater Than Zero](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-elements-must-not-have-tabindex-greater-than-zero/)** — Warning · High — A tabindex attribute must never have a value greater than 0 to prevent an unexpected tab order that can give the appearance of skipping some elements entirely. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – ARIA Dialog & Alertdialog Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-aria-dialog-alertdialog-require-accessible-name/)** — Warning · High — Aria dialog elements must have discernible text that clearly describes the destination, purpose, function, or action for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – ARIA Treeitem Nodes Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-aria-treeitem-nodes-require-accessible-name/)** — Warning · High — Aria treeitem elements must have discernible text that clearly describes the destination, purpose, function, or action for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Role=text Should Have No Focusable Descendants](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-roletext-should-have-no-focusable-descendants/)** — Warning · High — Elements with role=”text” must not have focusable descendants. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Form Elements Should Have Visible Label](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-form-elements-should-have-visible-label/)** — Warning · High — Form <input> elements may be given a title using the title or aria-describedby attributes – but not both. These attributes are used to provide additional information, such as a hint. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Frames Should Be Tested With axe-core](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-frames-should-be-tested-with-axe-core/)** — Warning · High — Frames must be tested with axe-core. Without it, it is not possible for the tool to perform violation checking on multiple levels of nested iframes. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Scope Attribute Should Be Used Correctly On Tables](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-scope-attribute-should-be-used-correctly-on-tables/)** — Warning · High — The scope attribute must be used correctly on tables in accordance with either HTML4 or HTML5 specifications to enable efficient table navigation for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Scrollable Region Requires Keyboard Access](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-scrollable-region-requires-keyboard-access/)** — Warning · High — Elements that have scrollable content should be accessible by keyboard. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Required ARIA Attributes Must Be Provided](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-required-aria-attributes-must-be-provided/)** — Warning · High — ARIA widget roles must have appropriate attributes describing the state or properties of the widget. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Attribute Must Be Used As Specified For Role](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-attribute-must-be-used-as-specified-for-role/)** — Warning · High — Some ARIA attributes are only allowed on an element under certain conditions. This rule flags ARIA attributes that are not used in a way that their role describes. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Attributes Require Valid Values](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-attributes-require-valid-values/)** — Warning · High — ARIA attributes starting with aria- must contain valid values. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Attributes Require Valid Names](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-attributes-require-valid-names/)** — Warning · High — ARIA attributes starting with aria- must have valid names. This rule will pick up misspelled attributes or any that do not exist. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Commands Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-commands-require-accessible-name/)** — Warning · High — ARIA command elements must have discernible text that clearly describes the destination, purpose, function, or action for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Input Fields Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-input-fields-require-accessible-name/)** — Warning · High — Accessible names must exist for the following input field roles – combobox, listbox, searchbox, slider, spinbutton and textbox. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Meter Nodes Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-meter-nodes-require-accessible-name/)** — Warning · High — Aria meter elements must have discernible text that clearly describes the destination, purpose, function, or action for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Progressbar Nodes Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-progressbar-nodes-require-accessible-name/)** — Warning · High — Aria progressbar elements must have discernible text that clearly describes the destination, purpose, function, or action for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Roles Must Be Contained By Required Parent](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-roles-must-be-contained-by-required-parent/)** — Warning · High — Certain ARIA roles must be contained by particular parent roles in order to perform the intended accessibility functions. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Roles Require Valid Values](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-roles-require-valid-values/)** — Warning · High — Values assigned to ARIA role values must be valid. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Toggle Fields Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-toggle-fields-require-accessible-name/)** — Warning · High — ARIA toggle fields must have an accessible name. This rule checks every element with a semantic role including checkbox, menu, menuitemcheckbox, menuitemradio, radio, radiogroup and switch. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – ARIA Tooltip Nodes Require Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-tooltip-nodes-require-accessible-name/)** — Warning · High — Aria tooltip elements must have discernible text that clearly describes the destination, purpose, function, or action for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Certain ARIA Roles Must Contain Specific Children](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-certain-aria-roles-must-contain-specific-children/)** — Warning · High — Some ARIA parent role values applied to elements must contain specific child elements and role values to perform intended accessibility function. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Aria-braille Require Non-braille Equivalent](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-braille-require-non-braille-equivalent/)** — Warning · High — WAI-ARIA requires that the aria-braillelabel attribute is only ever used on elements with an accessible name, such as from aria-label. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Aria-hidden Elements Contains Focusable Elements](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-hidden-elements-contains-focusable-elements/)** — Warning · High — This rule checks aria-hidden elements do not contain focusable elements. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Aria-hidden=true Must Not Be Used In <body>](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-aria-hiddentrue-must-not-be-used-in-body/)** — Warning · High — Document content is not accessible to assistive technology if <body aria-hidden=”true”>. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Elements Must Only Use Permitted ARIA Attributes](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-elements-must-only-use-permitted-aria-attributes/)** — Warning · High — Not all ARIA role-attribute combinations are valid. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Elements Must Use Allowed ARIA Attributes](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-elements-must-use-allowed-aria-attributes/)** — Warning · High — Not all ARIA role-attribute combinations are valid. Using ARIA attributes in roles where they are not allowed can interfere with the accessibility of the web page. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – IDs Used In ARIA & Labels Must Be Unique](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-ids-used-in-aria-labels-must-be-unique/)** — Warning · High — The value assigned to an id attribute used in ARIA or in form labels must be unique to prevent the second instance from being overlooked by assistive technology. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Page Requires Means To Bypass Repeated Blocks](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-page-requires-means-to-bypass-repeated-blocks/)** — Warning · High — Each page must have a main landmark to provide a mechanism to bypass repeated blocks of content or interface elements (like header and navigation) and quickly arrive at the main content. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Form <input> Elements Require Labels](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-form-input-elements-require-labels/)** — Warning · High — Each form element must have a programmatically associated label element. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Frames Require Title Attribute](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-frames-require-title-attribute/)** — Warning · High — All frame or iframe elements in the document must have a title that is not empty to describe their contents to screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Frames Require Unique Title Attribute](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-frames-require-unique-title-attribute/)** — Warning · High — All frame or iframe elements in the document must have a unique title to describe their contents to screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Frames With Focusable Content Must Not Use tabindex=-1](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-frames-with-focusable-content-must-not-use-tabindex-1/)** — Warning · High — <frame> and <iframe>; elements with focusable content must not have tabindex=”-1″. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Page Must Contain <title>](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-page-must-contain-title/)** — Warning · High — The HTML document must have a title element to provide users with an overview of its content, and when present, it must not be empty. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – HTML Element Lang Attribute Value Must Be Valid](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-html-element-lang-attribute-value-must-be-valid/)** — Warning · High — The HTML document must contain a valid lang attribute or must correspond to a valid lang code for multilingual screen reader users who may prefer a language other than the default. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – HTML Element Requires Lang Attribute](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-html-element-requires-lang-attribute/)** — Warning · High — The HTML document element must contain a valid lang attribute or must correspond to a valid lang code for multilingual screen reader users who may prefer a language other than the default. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Image Button Requires Alternate Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-image-button-requires-alternate-text/)** — Warning · High — <input type=”image”> must not have an empty alt, aria-label or aria-labelledby attribute. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Images Require Alternate Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-images-require-alternate-text/)** — Warning · High — All images must have alternate text to convey their purpose and meaning to screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – <object> Elements Require Alternate Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-object-elements-require-alternate-text/)** — Warning · High — All embedded objects must have text alternatives to be read out to screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Active <area> Elements Require Alternate Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-active-area-elements-require-alternate-text/)** — Warning · High — An image map is a single image with many clickable areas. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Elements Marked role=img Require Alternate Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-elements-marked-roleimg-require-alternate-text/)** — Warning · High — Elements with the role=”img” attribute value must also contain markup specifying accessible alternative text describing the image. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – SVG Images & Graphics Require Accessible Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-svg-images-graphics-require-accessible-text/)** — Warning · High — SVG elements with an <img>, graphics-document or graphics-symbol role must have an accessible text alternative. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – <video> Elements Require <track> For Captions](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-video-elements-require-track-for-captions/)** — Warning · High — An HTML5 video element must include a track element with kind=”captions” set as a property. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – <video> or <audio> Elements Must Not Auto-play](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-video-or-audio-elements-must-not-auto-play/)** — Warning · High — <video> or <audio> elements must not autoplay audio for more than 3 seconds without a control mechanism to stop or mute the audio. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Buttons Require Discernible Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-buttons-require-discernible-text/)** — Warning · High — Buttons must have discernible text that clearly describes the destination, purpose, function, or action for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Input Buttons Require Discernible Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-input-buttons-require-discernible-text/)** — Warning · High — Input buttons must have discernible text, as screen reader users are not able to discern the purpose of an input type=”button” without an accessible name. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Links Require Discernible Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-links-require-discernible-text/)** — Warning · High — Link text and alternate text for images, when used as links, must be discernible by a screen reader, must not have a duplicate label, and must be focusable. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Links Must Be Distinguishable](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-links-must-be-distinguishable/)** — Warning · High — Ensures users who cannot distinguish between colors can tell when text is a link by verifying the link has either a distinct style that does not rely on color or has a contrast difference of greater than 3:1 (which alerts you that manual testing is required). _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Select Element Requires Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-select-element-requires-accessible-name/)** — Warning · High — Each select element must have a programmatically associated label element. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Summary Elements Require Discernible Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-summary-elements-require-discernible-text/)** — Warning · High — Summary elements are used as a control for expanding and collapsing the details element. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Deprecated <marquee> Element Must Not Be Used](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-deprecated-marquee-element-must-not-be-used/)** — Warning · High — <marquee> elements must not be present because they are deprecated, increase difficulty for users with limited dexterity, and are distracting for users with cognitive or attention deficits. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Interactive Controls Must Not Be Nested](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-interactive-controls-must-not-be-nested/)** — Warning · High — Nested interactive controls are not announced by screen readers. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – List Items Must Be Contained In List Elements](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-list-items-must-be-contained-in-list-elements/)** — Warning · High — All list items (<li>) must be contained within <ul> or <ol> parent elements. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Lists Must Only Contain <li> Content Elements](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-lists-must-only-contain-li-content-elements/)** — Warning · High — Lists must be marked up correctly, meaning they must not contain content elements other than li elements. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – <dt> & <dd> Elements Must Be Contained by <dl>](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-dt-dd-elements-must-be-contained-by-dl/)** — Warning · High — Definition list items (dt and/or dd) must be wrapped in parent dl elements to be valid. This enables screen reader users to understand the proper hierarchy of information in the list. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – <dl> Must Only Have Ordered <dt> & <dd> Groups](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-dl-must-only-have-ordered-dt-dd-groups/)** — Warning · High — Definition lists (dl) must contain only properly-ordered dt and dd groups, div, script, or template elements. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – <blink> Elements Deprecated & Must Not Be Used](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-blink-elements-deprecated-must-not-be-used/)** — Warning · High — This rule requires that no blink elements are present. Flashing text can be difficult to read and blinking objects can be difficult to activate. The associated automated check finds the presence of all blink elements so that they can be removed. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – <th> Element Requires Associated Data Cells](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-th-element-requires-associated-data-cells/)** — Warning · High — Markup tables semantically and with the correct header structure. Screen readers have features to ease table navigation, but tables must be marked up accurately for these features to work correctly. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Table Header Attr Must Refer To Cell In Same Table](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-table-header-attr-must-refer-to-cell-in-same-table/)** — Warning · High — This rule checks that references to header columns and rows connect to specific td elements. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 AA – Meta Viewport Zoom & Scaling Disabled](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-aa-meta-viewport-zoom-scaling-disabled/)** — Warning · High — The document must not use the user-scalable=”no” parameter in the element because it disables text scaling and zooming which is essential to users with low vision. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 AA – Lang Attribute Requires Valid Value](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-aa-lang-attribute-requires-valid-value/)** — Warning · High — The language specified in the HTML document must be one of the valid languages to ensure text is pronounced correctly for screen reader users. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 AA – Text Requires Higher Color Contrast to Background](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-aa-text-requires-higher-color-contrast-to-background/)** — Warning · High — All text elements must have sufficient contrast between text in the foreground and background colors behind it in accordance with WCAG 2 AA contrast ratio thresholds. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 AAA – Text Requires Higher Color Contrast Ratio](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-aaa-text-requires-higher-color-contrast-ratio/)** — Warning · High — All text elements must have sufficient contrast between text in the foreground and background colors behind it in accordance with WCAG 2 AAA contrast ratio thresholds. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.1 AA – Autocomplete Attribute Must Be Used Correctly](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-1-aa-autocomplete-attribute-must-be-used-correctly/)** — Warning · High — The purpose for each common input field that collects an individual’s personal data is programmatically defined based on the list of 53 Input Purposes for User Interface Components. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.1 AA – Inline Text Spacing Must Be Adjustable](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-1-aa-inline-text-spacing-must-be-adjustable/)** — Warning · High — Inline text spacing must be adjustable with custom stylesheets. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.2 AA – Touch Targets Require Sufficient Size & Spacing](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-2-aa-touch-targets-require-sufficient-size-spacing/)** — Warning · High — Touch targets must be at least 24 by 24 CSS pixels in size. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Skip-link Target Should Exist & Be Focusable](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-skip-link-target-should-exist-be-focusable/)** — Warning · Medium — The page must have a link at the top before the navigation that allows users to skip lengthy navigation and proceed to a page’s main content to save time. _Trigger:_ To populate this filter ‘Accessibility’ must be enabled via ‘Config > Spider > Extraction’ and ‘JavaScript rendering’ mode via ‘Config > Spider > Rendering’.
- **[Best Practice – All Page Content Must Be Contained By Landmarks](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-all-page-content-must-be-contained-by-landmarks/)** — Warning · Medium — It’s best practice to contain all content excepting skip links, within distinct regions such as the header, nav, main, and footer. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Page Requires One Main Landmark](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-page-requires-one-main-landmark/)** — Warning · Medium — It’s best practice to ensure that there is only one main landmark to navigate to the primary content of the page and that if the page contains iframe elements, each should either contain no landmarks, or just a single landmark. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Page Must Not Have More Than One Banner Landmark](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-page-must-not-have-more-than-one-banner-landmark/)** — Warning · Medium — The role=”banner” ARIA landmark should only appear once on an element that is unique to the HTML document. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Banner Landmark Must Not Be In Another Landmark](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-banner-landmark-must-not-be-in-another-landmark/)** — Warning · Medium — For each element on the page that uses the role=”banner” ARIA landmark, ensure that it is not contained within another ARIA landmark. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Page Must Not Have Multiple Contentinfo Landmarks](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-page-must-not-have-multiple-contentinfo-landmarks/)** — Warning · Medium — A page should not contain more than one instance of the contentinfo landmark. The ARIA specification states the landmark role=”contentinfo” are meant to be used only once per page. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Page Requires At Most One Main Landmark](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-page-requires-at-most-one-main-landmark/)** — Warning · Medium — It is a best practice to ensure that there is only one main landmark to navigate to the primary content of the page and that if the page contains iframe elements, each should either contain no landmarks, or just a single landmark. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Complementary Landmarks & Asides Must Be Top Level](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-complementary-landmarks-asides-must-be-top-level/)** — Warning · Medium — This best practice rule ensures that aside elements or elements with role=complementary are not an internal part of another ARIA landmark. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Contentinfo Landmark Must Be Top Level Landmark](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-contentinfo-landmark-must-be-top-level-landmark/)** — Warning · Medium — Text content should be contained within a landmark region, the role=”contentinfo” ARIA landmark should be used on an element that is outside of other landmarks used on the page, since footer information is generally separated from the header and main body content. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Main Landmark Must Not Be In Another Landmark](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-main-landmark-must-not-be-in-another-landmark/)** — Warning · Medium — It is a best practice to ensure the main landmark is not contained within another landmark. All content should be contained within distinct regions such as the header (role=”banner”), content (role=”main”), and footer (role=”contentinfo”). _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Landmarks Require Unique Role Or Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-landmarks-require-unique-role-or-accessible-name/)** — Warning · Medium — Landmarks must have a unique role or role/label/title (i.e. accessible name) combination. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Page Must Contain <h1>](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-page-must-contain-h1/)** — Warning · Medium — Ensures that the page, or at least one of its frames, contains an h1 element that appears before the start of the main content. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Heading Levels Should Only Increase By One](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-heading-levels-should-only-increase-by-one/)** — Warning · Medium — Headings must be in a valid logical order, meaning h1 through h6 element tags must appear in a sequentially-descending order. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Form Field Must Not Have Multiple Label Elements](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-form-field-must-not-have-multiple-label-elements/)** — Warning · Medium — Only one label should be assigned to a form field. Assigning multiple labels to the same form field can cause problems for some combinations of screen readers and browsers. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – HTML Lang & XML Lang Value Should Match](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-html-lang-xml-lang-value-should-match/)** — Warning · Medium — The HTML document must contain a valid lang attribute or must correspond to a valid lang code for multilingual screen reader users who may prefer a language other than the default. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Ensure Elements Marked Presentational Are Ignored](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-ensure-elements-marked-presentational-are-ignored/)** — Warning · Low — Elements marked as presentational should not have global ARIA or tabindex to ensure all screen readers ignore them. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – ARIA Role Should Be Appropriate For Element](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-aria-role-should-be-appropriate-for-element/)** — Warning · Low — Not all WAI-ARIA role values are allowed on every HTML element. This rule checks that each HTML element with an assigned role is allowed to have that role. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Headings Should Not Be Empty](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-headings-should-not-be-empty/)** — Warning · Low — It is a best practice to ensure all heading elements (those marked with h1 through h6) contain content and is accessible by a screen reader. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Meta Viewport Should Allow Zoom & Scale Up to 500%](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-meta-viewport-should-allow-zoom-scale-up-to-500/)** — Warning · Low — The document must not use the user-scalable=”no” parameter in the <meta name=”viewport”> element because it disables text scaling and zooming which is essential to users with low vision. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Alt Text Should Not Be Repeated As Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-alt-text-should-not-be-repeated-as-text/)** — Warning · Low — When button and link text repeats in a alt attribute value, screen reader users hear the same information twice, which renders the alt text meaningless and confusing. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Table Headers Require Discernible Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-table-headers-require-discernible-text/)** — Warning · Low — Table header elements should have visible text. Ensure that the table header can be used by screen reader users. If the element is not a header, marking it up with a `td` is more appropriate. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[Best Practice – Table With Identical Summary & Caption Text](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/best-practice-table-with-identical-summary-caption-text/)** — Warning · Low — Ensure the caption and summary table attributes are not identical. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Deprecated ARIA Roles Must Not Be Used](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-deprecated-aria-roles-must-not-be-used/)** — Warning · Low — Values assigned to ARIA role values must not be deprecated. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 A – Server-Side Image Maps Must Not Be Used](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-a-server-side-image-maps-must-not-be-used/)** — Warning · Low — The document contains an image map that is server-side instead of client-side. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 AAA – Delayed Meta Refresh Must Not Be Used](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-aaa-delayed-meta-refresh-must-not-be-used/)** — Warning · Low — The document must not use <meta http-equiv=”refresh”> because it can prevent control over when the refresh occurs for users with disabilities. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.
- **[WCAG 2.0 AAA – Links With Same Accessible Name](https://www.screamingfrog.co.uk/seo-spider/issues/accessibility/wcag-2-0-aaa-links-with-same-accessible-name/)** — Warning · Low — This rule checks links with the same accessible name serve a similar purpose. _Trigger:_ Please view the Deque University website further reading link below for ruleset triggers.

## Analytics (4)

_The Google Analytics API can pull in data directly into the crawl for additional insight in technical and content audits. Find issues related to orphan URLs only discovered in Google Analytics, non-indexable URLs with GA data and more._

- **[Orphan URLs](https://www.screamingfrog.co.uk/seo-spider/issues/analytics/analytics-orphan-urls/)** — Issue · Medium — URLs that have been discovered via Google Analytics, rather than internal links during a crawl. _Trigger:_ This issue is triggered when URLs are discovered through Google Analytics API data rather than being found through internal links during a website crawl.
- **[Bounce Rate Above 70%](https://www.screamingfrog.co.uk/seo-spider/issues/analytics/bounce-rate-above-70/)** — Warning · Low — URLs that have a bounce rate over 70% in Google Analytics, which you may wish to investigate. _Trigger:_ This issue is triggered when URLs have a bounce rate over 70% as reported in Google Analytics.
- **[No GA Data](https://www.screamingfrog.co.uk/seo-spider/issues/analytics/no-ga-data/)** — Warning · Low — URLs returning no data for the metrics and dimensions queried via the Google Analytics API. _Trigger:_ This issue is triggered when URLs return no data for the metrics and dimensions queried via the Google Analytics API.
- **[Non-Indexable with GA Data](https://www.screamingfrog.co.uk/seo-spider/issues/analytics/non-indexable-with-ga-data/)** — Warning · Low — URLs that are classed as non-indexable, but have Google Analytics data. _Trigger:_ This issue is triggered when URLs are classified as non-indexable in a website crawl, yet they show activity in Google Analytics.

## Search Console (10)

_The Google Search Console API can collect click data directly into the crawl for additional insight and query the URL Inspection API to gather indexing data in bulk. Find issues related to orphan URLs, URLs without search analytics data, URLs not indexed and more._

- **[Page is Not Mobile Friendly](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/page-is-not-mobile-friendly/)** — Issue · High — URLs that have usability issues on mobile devices. _Trigger:_ This issue is triggered when URLs have usability issues on mobile devices.
- **[Orphan URLs](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/search-console-orphan-urls/)** — Issue · Medium — URLs that have been discovered in the performance report in Google Search Console, rather than internal links during a crawl. _Trigger:_ This issue is triggered when URLs are discovered through the performance report in Google Search Console, but are not found through internal links during a website crawl.
- **[URL is on Google, But Has Issues](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/url-is-on-google-but-has-issues/)** — Issue · Medium — URLs that have been indexed and can appear in Google Search results, but there are some problems with mobile usability, AMP or Rich results that might mean it doesn’t appear in an optimal way. _Trigger:_ This issue is triggered when URLs have been indexed and can appear in Google Search results, but there are identified problems related to mobile usability, AMP or Rich Results.
- **[AMP URL is Invalid](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/amp-url-is-invalid/)** — Issue · Medium — AMP URLs that have an error that will prevent it from being indexed. _Trigger:_ This issue is triggered when AMP URLs have errors that prevent them from being indexed.
- **[Rich Result is Invalid](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/rich-result-is-invalid/)** — Issue · Medium — URLs that have an error with one or more rich result enhancements that will prevent the rich result from showing in the Google search results. _Trigger:_ This issue is triggered when URLs have errors with one or more rich result enhancements, which will prevent the rich results from being displayed in Google search results.
- **[Indexable URL Not Indexed](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/indexable-url-not-indexed/)** — Warning · High — URLs found in the crawl that are indexable, but are not indexed by Google and won’t appear in the search results. _Trigger:_ This issue is triggered when URLs found during a website crawl are deemed indexable but are not indexed by Google, meaning they won’t appear in search results.
- **[User-Declared Canonical Not Selected](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/user-declared-canonical-not-selected/)** — Warning · Medium — Google has chosen to index a different URL to the one declared by the user in the HTML or HTTP Header. _Trigger:_ This issue is triggered when Google, in its indexing process, chooses to index a different URL than the one declared as the canonical by the user in the HTML or HTTP Header.
- **[No Search Analytics Data](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/no-search-analytics-data/)** — Warning · Low — URLs that are not returning impressions in the performance report in Google Search Console. _Trigger:_ This issue is triggered when URLs do not return any impressions in the performance report in Google Search Console.
- **[Non-Indexable with Search Analytics Data](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/non-indexable-with-search-analytics-data/)** — Warning · Low — URLs that are classed as non-indexable, but have recorded impressions in the performance report in Google Search Console. _Trigger:_ This issue is triggered when URLs are classified as non-indexable in a website crawl – but have recorded impressions in the performance report in Google Search Console.
- **[URL Is Not on Google](https://www.screamingfrog.co.uk/seo-spider/issues/search-console/url-is-not-on-google/)** — Warning · Low — URLs not indexed by Google and won’t appear in the search results. _Trigger:_ This issue is triggered when URLs are not indexed by Google, meaning they won’t appear in search results.

## Validation (10)

_Valid HTML helps crawlers parse and understand web pages accurately and errors could impact crawlers when crawling and indexing. Find issues that can impact search bots from being able to parse and understand a page reliably._

- **[Missing <head> Tag](https://www.screamingfrog.co.uk/seo-spider/issues/validation/missing-head-tag/)** — Issue · High — Pages missing a <head> element within the HTML. _Trigger:_ This issue is triggered when pages are missing a <head> element within the HTML.
- **[Multiple <head> Tags](https://www.screamingfrog.co.uk/seo-spider/issues/validation/multiple-head-tags/)** — Issue · High — Pages with multiple <head> elements in the HTML. _Trigger:_ This issue is triggered when pages have multiple <head> elements within the HTML.
- **[Missing <body> Tag](https://www.screamingfrog.co.uk/seo-spider/issues/validation/missing-body-tag/)** — Issue · High — Pages missing a <body> element within the HTML. _Trigger:_ This issue is triggered when pages are missing a <body> element within the HTML.
- **[Multiple <body> Tags](https://www.screamingfrog.co.uk/seo-spider/issues/validation/multiple-body-tags/)** — Issue · High — Pages with multiple <body> elements in the HTML. _Trigger:_ This issue is triggered when pages contain multiple <body> elements within the HTML.
- **[HTML Document Over 2MB](https://www.screamingfrog.co.uk/seo-spider/issues/validation/html-document-over-2mb/)** — Issue · High — Pages which are over 2mb in document size. This is important as Googlebot limit their crawling and indexing to the first 2mb of an HTML file or supported text-based file. _Trigger:_ This issue is triggered when pages are over 2mb in document size.
- **[Resource Over 2MB](https://www.screamingfrog.co.uk/seo-spider/issues/validation/resource-over-2mb/)** — Issue · High — JavaScript and CSS files which are over 2mb in size. This is important as Googlebot limit their crawling and indexing to the first 2mb of a file. _Trigger:_ This issue is triggered when JavaScript or CSS files are over 2mb in size.
- **[Invalid HTML Elements In <head>](https://www.screamingfrog.co.uk/seo-spider/issues/validation/invalid-html-elements-in-head/)** — Warning · High — Pages with invalid HTML elements within the <head> . When an invalid element is used in the <head> , Google assumes the end of the <head> element and ignores any elements that appear after the invalid element. _Trigger:_ This issue is triggered when pages contain invalid HTML elements within the <head> section.
- **[<body> Element Preceding <html>](https://www.screamingfrog.co.uk/seo-spider/issues/validation/body-element-preceding-html/)** — Warning · High — Pages that have a body element (such as a <div> , <p> or <img> etc) preceding the opening <html> element. _Trigger:_ This issue is triggered when pages have a <body> element that precedes the opening <html> element.
- **[<head> Not First In <html> Element](https://www.screamingfrog.co.uk/seo-spider/issues/validation/head-not-first-in-html-element/)** — Warning · High — Pages with an HTML element that proceed the <head> element in the HTML. The <head> should be the first element in the <html> element. _Trigger:_ This issue is triggered when pages have an HTML element other than the <head> preceding the <head> element within the <html> structure.
- **[High Carbon Rating](https://www.screamingfrog.co.uk/seo-spider/issues/validation/high-carbon-rating/)** — Opportunity · Low — Pages that have a carbon rating of F using the digital carbon ratings system from Sustainable Web Design. _Trigger:_ This issue is triggered when a URL is assigned a carbon rating of F using the digital carbon ratings system from Sustainable Web Design.

---

# Part 2 — Main-window tabs & all filters

Source: /user-guide/tabs/. Includes informational (non-issue) filters, e.g. Internal content-type filters, Directives: Index/Follow, Canonicals: Self Referencing. Every tab also has an implicit "All" filter.

Main-window tabs (in order): Internal, External, Security, Response Codes, URL, Page Titles, Meta Description, Meta Keywords, H1, H2, Content, Images, Canonicals, Pagination, Directives, Hreflang, JavaScript, Links, AMP, Structured Data, Sitemaps, PageSpeed, Mobile, Accessibility, Custom Search, Custom Extraction, Custom JavaScript, Analytics, Search Console, Validation, Link Metrics, AI, Change Detection (compare mode).


### Internal (8 filters)

- HTML
- JavaScript
- CSS
- Images
- PDF
- Flash
- Other
- Unknown

### External (8 filters)

- HTML
- JavaScript
- CSS
- Images
- PDF
- Flash
- Other
- Unknown

### Security (13 filters)

- HTTP URLs
- HTTPS URLs
- Mixed Content
- Form URL Insecure
- Form on HTTP URL
- Unsafe Cross-Origin Links
- Protocol-Relative Resource Links
- Missing HSTS Header
- Missing Content-Security-Policy Header
- Missing X-Content-Type-Options Header
- Missing X-Frame-Options Header
- Missing Secure Referrer-Policy Header
- Bad Content Type

### Response Codes (12 filters)

- Blocked by Robots.txt
- Blocked Resource
- No Response
- Success (2XX)
- Redirection (3XX)
- Redirection (JavaScript)
- Redirection (Meta Refresh)
- Redirection (HTTP Refresh)
- Redirect Chain
- Redirect Loop
- Client Error (4xx)
- Server Error (5XX)

### URL (11 filters)

- Non ASCII Characters
- Underscores
- Uppercase
- Multiple Slashes
- Repetitive Path
- Contains A Space
- Internal Search
- Parameters
- Broken Bookmark
- GA Tracking Parameters
- Over 115 characters

### Page titles (9 filters)

- Missing
- Duplicate
- Over 60 characters
- Below 30 characters
- Over X Pixels
- Below X Pixels
- Same as h1
- Multiple
- Outside <head>

### Meta description (8 filters)

- Missing
- Duplicate
- Over 155 characters
- Below 70 characters
- Over X Pixels
- Below X Pixels
- Multiple
- Outside <head>

### Meta keywords (3 filters)

- Missing
- Duplicate
- Multiple

### h1 (6 filters)

- Missing
- Duplicate
- Over 70 characters
- Multiple
- Alt Text in h1
- Non-sequential

### h2 (5 filters)

- Missing
- Duplicate
- Over 70 characters
- Multiple
- Non-sequential

### Content (9 filters)

- Exact Duplicates
- Near Duplicates
- Low Content Pages
- Soft 404 Pages
- Spelling Errors
- Grammar Errors
- Readability Difficult
- Readability Very Difficult
- Lorem Ipsum Placeholder

### Images (7 filters)

- Over 100kb
- Missing Alt Text
- Missing Alt Attribute
- Alt Text Over 100 Characters
- Background Images
- Missing Size Attributes
- Incorrectly Sized Images

### Canonicals (12 filters)

- Contains Canonical
- Self Referencing
- Canonicalised
- Missing
- Multiple
- Multiple Conflicting
- Non-Indexable Canonical
- Canonical Is Relative
- Unlinked
- Invalid Attribute In Annotation
- Contains Fragment URL
- Outside <head>

### Pagination (10 filters)

- Contains Pagination
- First Page
- Paginated 2+ Pages
- Pagination URL Not In Anchor Tag
- Non-200 Pagination URL
- Unlinked Pagination URL
- Non-Indexable
- Multiple Pagination URLs
- Pagination Loop
- Sequence Error

### Directives (17 filters)

- Index
- Noindex
- Follow
- Nofollow
- None
- NoArchive
- NoSnippet
- Max-Snippet
- Max-Image-Preview
- Max-Video-Preview
- NoODP
- NoYDIR
- NoImageIndex
- NoTranslate
- Unavailable_After
- Refresh
- Outside <head>

### hreflang (14 filters)

- Contains Hreflang
- Non-200 Hreflang URLs
- Unlinked Hreflang URLs
- Missing Return Links
- Inconsistent Language & Region Return Links
- Non-Canonical Return Links
- Noindex Return Links
- Incorrect Language & Region Codes
- Multiple Entries
- Missing Self Reference
- Not Using Canonical
- Missing X-Default
- Missing
- Outside <head>

### JavaScript (16 filters)

- Pages with Blocked Resources
- Contains JavaScript Links
- Contains JavaScript Content
- Noindex Only in Original HTML
- Nofollow Only in Original HTML
- Canonical Only in Rendered HTML
- Canonical Mismatch
- Page Title Only in Rendered HTML
- Page Title Updated by JavaScript
- Meta Description Only in Rendered HTML
- Meta Description Updated by JavaScript
- H1 Only in Rendered HTML
- H1 Updated by JavaScript
- Uses Old AJAX Crawling Scheme URLs
- Uses Old AJAX Crawling Scheme Meta Fragment Tag
- Pages with JavaScript Errors

### Links (11 filters)

- Pages With High Crawl Depth
- Pages Without Internal Outlinks
- Internal Nofollow Outlinks
- Internal Outlinks With No Anchor Text
- Non-Descriptive Anchor Text In Internal Outlinks
- Pages With High External Outlinks
- Pages With High Internal Outlinks
- Follow & Nofollow Internal Inlinks To Page
- Internal Nofollow Inlinks Only
- Outlinks To Localhost
- Non-Indexable Page Inlinks Only

### AMP (17 filters)

- Non-200 Response
- Missing Non-AMP Return Link
- Missing Canonical to Non-AMP
- Non-Indexable Canonical
- Indexable
- Non-Indexable
- Missing HTML AMP Tag
- Missing/Invalid Doctype HTML Tag
- Missing Head Tag
- Missing Body Tag
- Missing Canonical
- Missing/Invalid Meta Charset Tag
- Missing/Invalid Meta Viewport Tag
- Missing/Invalid AMP Script
- Missing/Invalid AMP Boilerplate
- Contains Disallowed HTML
- Other Validation Errors

### Structured data (8 filters)

- Contains Structured Data
- Missing Structured Data
- Validation Errors
- Validation Warnings
- Parse Errors
- Microdata URLs
- JSON-LD URLs
- RDFa URLs

### Sitemaps (7 filters)

- URLs In Sitemap
- URLs Not In Sitemap
- Orphan URLs
- Non-Indexable URLs in Sitemap
- URLs In Multiple Sitemaps
- XML Sitemap With Over 50k URLs
- XML Sitemap With Over 50mb

### PageSpeed (19 filters)

- Document Request Latency
- LCP Request Discovery
- Render Blocking Requests
- Network Dependency Tree
- Use Efficient Cache Lifetimes
- Layout Shift Culprits
- Improve Image Delivery
- Forced Reflow
- Legacy JavaScript
- Duplicated JavaScript
- Avoid Enormous Network Payloads
- Minify CSS
- Minify JavaScript
- Reduce Unused CSS
- Reduce Unused JavaScript
- Reduce JavaScript Execution Time
- Minimize Main-Thread Work
- Optimize DOM Size
- Font Display

### Mobile (6 filters)

- Viewport Not Set
- Target Size
- Content Not Sized Correctly
- Illegible Font Size
- Unsupported Plugins
- Mobile Alternate Link

### Accessibility (96 filters)

- Accessibility Score Poor
- Accessibility Score Needs Improvement
- Accessibility Score Good
- Accesskey Attribute Value Must Be Unique
- Ensure Elements Marked Presentational Are Ignored
- Elements Must Not Have Tabindex Greater Than Zero
- Skip-link Target Should Exist & Be Focusable
- Role=text Should Have No Focusable Descendants
- ARIA Dialog & Alertdialog Require Accessible Name
- ARIA Role Should Be Appropriate For Element
- ARIA Treeitem Nodes Require Accessible Name
- All Page Content Must Be Contained By Landmarks
- Page Requires One Main Landmark
- Page Must Not Have More Than One Banner Landmark
- Banner Landmark Must Not Be In Another Landmark
- Page Must Not Have Multiple Contentinfo Landmarks
- Page Requires At Most One Main Landmark
- Complementary Landmarks & Asides Must Be Top Level
- Contentinfo Landmark Must Be Top Level Landmark
- Main Landmark Must Not Be In Another Landmark
- Landmarks Require Unique Role Or Accessible Name
- Form Elements Should Have Visible Label
- Frames Should Be Tested With axe-core
- Page Must Contain <h1>
- Heading Levels Should Only Increase By One
- Headings Should Not Be Empty
- Meta Viewport Should Allow Zoom & Scale Up to 500%
- Alt Text Should Not Be Repeated As Text
- Table Headers Require Discernible Text
- Table With Identical Summary & Caption Text
- Scope Attribute Should Be Used Correctly On Tables
- Scrollable Region Requires Keyboard Access
- Required ARIA Attributes Must Be Provided
- ARIA Attribute Must Be Used As Specified For Role
- ARIA Attributes Require Valid Values
- ARIA Attributes Require Valid Names
- ARIA Commands Require Accessible Name
- ARIA Input Fields Require Accessible Name
- ARIA Meter Nodes Require Accessible Name
- ARIA Progressbar Nodes Require Accessible Name
- ARIA Roles Must Be Contained By Required Parent
- ARIA Roles Require Valid Values
- ARIA Toggle Fields Require Accessible Name
- ARIA Tooltip Nodes Require Accessible Name
- Certain ARIA Roles Must Contain Specific Children
- Deprecated ARIA Roles Must Not Be Used
- Aria-braille Require Non-braille Equivalent
- Aria-hidden Elements Contains Focusable Elements
- Aria-hidden=true Must Not Be Used In <body>
- Elements Must Only Use Permitted ARIA Attributes
- Elements Must Use Allowed ARIA Attributes
- IDs Used In ARIA & Labels Must Be Unique
- Page Requires Means To Bypass Repeated Blocks
- Form <input> Elements Require Labels
- Form Field Must Not Have Multiple Label Elements
- Frames Require Title Attribute
- Frames Require Unique Title Attribute
- Frames With Focusable Content Must Not Use tabindex=-1
- Page Must Contain <title>
- HTML Element Lang Attribute Value Must Be Valid
- HTML Element Requires Lang Attribute
- HTML Lang & XML Lang Value Should Match
- Timed Meta Refresh Must Not Exist
- Image Button Requires Alternate Text
- Images Require Alternate Text
- <object> Elements Require Alternate Text
- Active <area> Elements Require Alternate Text
- Elements Marked role=img Require Alternate Text
- SVG Images & Graphics Require Accessible Text
- Server-Side Image Maps Must Not Be Used
- <video> Elements Require <track> For Captions
- <video> or <audio> Elements Must Not Auto-play
- Buttons Require Discernible Text
- Input Buttons Require Discernible Text
- Links Must Be Distinguishable
- Links Require Discernible Text
- Select Element Requires Accessible Name
- Summary Elements Require Discernible Text
- Deprecated <marquee> Element Must Not Be Used
- <blink> Elements Deprecated & Must Not Be Used
- Interactive Controls Must Not Be Nested
- List Items Must Be Contained In List Elements
- Lists Must Only Contain <li> Content Elements
- <dl> Must Only Have Ordered <dt> & <dd> Groups
- <dt> & <dd> Elements Must Be Contained by <dl>
- <th> Element Requires Associated Data Cells
- Table Header Attr Must Refer To Cell In Same Table
- Meta Viewport Zoom & Scaling Disabled
- Lang Attribute Requires Valid Value
- Text Requires Higher Color Contrast to Background
- Delayed Meta Refresh Must Not Be Used
- Links With Same Accessible Name
- Text Requires Higher Color Contrast Ratio
- Autocomplete Attribute Must Be Used Correctly
- Inline Text Spacing Must Be Adjustable
- Touch Targets Require Sufficient Size & Spacing

### Custom search (1 filters)

- [Search Filter Name]

### Custom extraction (1 filters)

- [Extractor Name]

### Custom JavaScript (1 filters)

- [Snippet Name]

### Analytics (5 filters)

- Sessions Above 0
- Bounce Rate Above 70%
- No GA Data
- Non-Indexable with GA Data
- Orphan URLs

### Search Console (11 filters)

- Clicks Above 0
- No Search Analytics Data
- Non-Indexable with Search Analytics Data
- Orphan URLs
- URL Is Not on Google
- Indexable URL Not Indexed
- URL is on Google, But Has Issues
- User-Declared Canonical Not Selected
- Page Is Not Mobile Friendly
- AMP URL Is Invalid
- Rich Result Invalid

### Validation (10 filters)

- Invalid HTML Elements In <head>
- <body> Element Preceding <html>
- <head> Not First In <html> Element
- Missing <head> Tag
- Multiple <head> Tags
- Missing <body> Tag
- Multiple <body> Tags
- HTML Document Over 2MB
- Resource Over 2mb
- High Carbon Rating

### AI (1 filters)

- [Prompt Name]

### Change Detection (14 filters)

- Indexability
- Page Titles
- Meta Description
- H1
- Word Count
- Crawl Depth
- Inlinks
- Unique Inlinks
- Internal Outlinks
- Unique Internal Outlinks
- External Outlinks
- Unique External Outlinks
- Structured Data Unique Types
- Content

### Link Metrics
- No fixed filters; columns from Majestic / Ahrefs / Moz at URL, subdomain or domain level.


### Lower-window (detail) tabs — shown for the URL selected in the main table
- URL Details — URL, status code, status, content type, size, crawl depth, inlinks, outlinks, URL-encoded address, etc.
- Inlinks — Type, From, To, Anchor Text, Alt Text, Follow, Target, Rel, Status Code, Status, Path Type, Link Path (XPath), Link Position, Link Origin (HTML / Rendered HTML / both / Dynamically Loaded).
- Outlinks — same columns as Inlinks, for links out of the page (incl. "Link Crawlability" column for uncrawlable links).
- Image Details — From, To, Alt Text, Real Dimensions, Dimensions in Attributes, Display Dimensions, Potential Savings, path/position/origin; image preview.
- Resources — JS/CSS/image etc. resources on the page with the same link columns.
- SERP Snippet — Google snippet emulator (pixel-width truncation, desktop/mobile/tablet), editable title/description.
- Rendered Page — screenshot of JS-rendered page + blocked/all resources list.
- View Source — original HTML (left) vs rendered HTML (right), searchable, exportable.
- HTTP Headers — request headers (left), response headers (right).
- Cookies — cookies per URL (name, value, domain, path, expiry, secure, HttpOnly…).
- Duplicate Details — exact & near duplicates with similarity %, diff highlighting.
- Structured Data Details — property tree + Validation Type, Issue Severity, Issue.
- Lighthouse Details — PSI metrics/opportunities per URL; Source Page, URL, Size (Bytes), Potential Savings.
- Accessibility Details — axe violations/incomplete/passed rules, guidelines, impact, location on page (Show Issue in Browser / in Rendered HTML).
- Spelling & Grammar Details — error, type, detail, suggestion, highlighted text.
- Chrome Console Log — JS errors/warnings/issues per page.
- N-grams — 1- to 6-gram phrase frequency for selected URL(s) (needs Store HTML).
- Crawl Path (export via right-click) — shortest discovery path to the URL.

### Right-hand pane tabs
- Overview — summary + SEO Elements (count per tab/filter, "Crawl Analysis Required" markers).
- Issues — every triggered issue with Issue Name, Type, Priority, URLs, % of Total, in-app description/tips; segments bar.
- Site Structure — aggregated directory tree (Path, URLs, Indexable, Non-Indexable; views by indexability status, response codes, crawl depth) + crawl-depth histogram 1–10+.
- Segments — per-segment URLs, % segmented, Indexable/Non-Indexable, Issues/Warnings/Opportunities, High/Medium/Low.
- Response Times — histogram of response-time buckets, number & % of URLs.
- API — progress and error counts for each connected API (GA, GSC, PSI, Majestic, Ahrefs, Moz, AI).
- Spelling & Grammar — top 100 unique errors and URLs affected (ignore rule / ignore all / add to dictionary).
- Semantic Search — query vs page embeddings cosine similarity; "Centroid" view for outliers / most representative page.


---

# Part 3 — Configuration options

Source: /user-guide/configuration/ (+ /user-guide/general/). Menu paths as in the app. Store = keep & show in UI; Crawl = request the URL / use it for discovery.

## 3.1 Spider > Crawl (resource & link types; each has independent Store / Crawl toggles)
- Images — `<img>` files: store / crawl (check response code). Images linked via `<a>` are always stored/crawled.
- Media — `<video>` / `<audio>` source files: store / crawl.
- CSS — stylesheets: store / crawl.
- JavaScript — script files: store / crawl.
- SWF — Flash files: store / crawl.
- Internal Hyperlinks — `<a href>` on the same subdomain: store / crawl (disable both in list mode to audit only the listed URLs).
- External Links — links to other domains (or other subdomains by default): store / crawl (incl. external images, CSS, JS, hreflang, canonicals).
- Canonicals — link element + HTTP header canonicals: store / crawl (use for discovery). Default on.
- Pagination (rel next/prev) — store / crawl. Default: not crawled.
- Hreflang — extract always shown; crawl hreflang URLs only if "Crawl hreflang" ticked (also extracts hreflang from XML sitemaps in list mode).
- AMP — `rel="amphtml"` URLs: store / crawl. Default off.
- Meta Refresh — URLs in meta refresh: store / crawl. Default on.
- iframes — URLs in iframes: store / crawl. Default on.
- Mobile Alternate — `rel="alternate" media=...` URLs: store / crawl. Default off.
- Uncrawlable Links — store links not in `<a href>` (e.g. `<span href>`, `onclick`, `javascript:` hrefs); shown in Outlinks with "Link Crawlability = Uncrawlable". Default off.
- Check Links Outside of Start Folder — when crawling a subfolder, still check (not crawl onward) links outside it.
- Crawl Outside of Start Folder — start in a subfolder but crawl the whole site.
- Crawl All Subdomains — treat all subdomains of the root domain as internal (root-domain start with no subdomain crawls all subdomains by default).
- Follow Internal "nofollow" / Follow External "nofollow" — crawl links with nofollow / sponsored / ugc, and from pages with meta/X-Robots nofollow.
- Crawl Invalid Links — parse & crawl syntactically invalid hrefs (e.g. `hppts://`, `https://example/`); reported as No Response / malformed.
- Crawl Linked XML Sitemaps — auto-discover via robots.txt and/or "Crawl These Sitemaps" list; needed for Sitemaps tab filters (post crawl analysis).

## 3.2 Spider > Extraction
- Page Details (each toggleable): Page Titles, Meta Descriptions, Meta Keywords, H1, H2, Indexability (& Indexability Status), Word Count, Readability, Text to Code Ratio, Hash Value (used for exact-duplicate detection), Page Size, Forms, Accessibility (axe-core, needs JS rendering).
- URL Details: Response Time, Last-Modified header, HTTP Headers (full request+response; also as columns in Internal tab), Cookies (disables auto-exclusion of GA tags).
- Directives: Meta Robots, X-Robots-Tag.
- Structured Data: JSON-LD, Microdata, RDFa; Schema.org Validation (types/properties exist, main + pending vocab, flags Data-Vocabulary.org); Google Rich Result Feature Validation (required props = errors, recommended = warnings); Case-Sensitive (schema.org case sensitivity; recommended off).
- HTML: Store HTML (original source → View Source, Bulk Export > All Page Source); Store Rendered HTML (post-JS DOM; needs JS rendering).
- PDF: Store PDF (save PDFs; view text in View Source); Extract PDF Properties (Subject, Author, Creation Date, Modification Date, Page Count, Word Count — title & keywords always extracted); Extract Link Text (anchor text of links inside PDFs).

## 3.3 Spider > Limits
- Limit Crawl Total (free = 500 URLs; licensed default 5M).
- Limit Crawl Depth (clicks from start URL).
- Limit URLs Per Crawl Depth.
- Limit Max Folder Depth (folders = path segments ending in `/`).
- Limit Number of Query Strings (skip URLs with more than N parameters).
- Limit Crawl Total Per Subdomain.
- Max Redirects to Follow.
- Max URL Length to Crawl (default 10,000 chars).
- Max Links per URL to Crawl (default 10,000).
- Max Page Size (KB) to Crawl (default 50 MB).
- Limit by URL Path (list of URL patterns, each with max pages).

## 3.4 Spider > Rendering
- Rendering mode: Text Only (raw HTML) / Old AJAX Crawling Scheme (`_escaped_fragment_`) / JavaScript (headless Chromium; also discovers raw-HTML links).
- Rendered Page Screenshots (on by default in JS mode) — window presets (Googlebot Desktop, Googlebot Smartphone, other devices) + Width & Height, Scaling Factor, Mobile flag, Touch Enabled flag, Resize to Content (up to 8192 px), Window Resize Time.
- JavaScript Error Reporting — Chrome console errors/warnings/issues → JavaScript tab filters, Chrome Console Log tab, report.
- Flatten Shadow DOM (default on).
- Flatten iframes (default on; inline iframe into parent like Google).
- Archive Website — save all HTML + resources as Hierarchical URL Archive (uncompressed folders) or WARC; "Open Archived Page in Browser".
- AJAX Timeout (seconds JS may run after load; default 5 s).
- Window Size (viewport; Googlebot mobile 411×731, desktop 1024×768, stretched up to 8,192 px).

## 3.5 Spider > Advanced
- Cookie Storage: Session Only (default) / Persistent (shared across threads, per crawl) / Do Not Store.
- Ignore Non-Indexable URLs for Issues (issue filters only for indexable pages: titles, meta, H1/H2, Low Content, Structured Data Missing/Validation, Orphan URLs, No GA Data, No Search Analytics Data, High Crawl Depth).
- Ignore Paginated URLs for Duplicate Filters (rel=prev pages excluded from Duplicate filters).
- Always Follow Redirects (list mode: follow to final target, ignoring crawl depth).
- Always Follow Canonicals (list mode: follow canonical chains).
- Respect Noindex (hide noindex URLs from UI, still crawl their links).
- Respect Canonical (hide canonicalised URLs from UI).
- Respect Next/Prev (hide rel=prev URLs from UI).
- Respect HSTS Policy (HTTP→HTTPS internally shown as 307 "HSTS Policy"; disable to see true redirect code).
- Respect Self Referencing Meta Refresh (treat self meta refresh as non-indexable; can disable).
- Extract Images From IMG SRCSET Attribute.
- Crawl Fragment Identifiers (treat `#fragment` URLs as unique).
- Perform HTML Validation (populates Validation tab and "Outside <head>" filters).
- Green Hosting Carbon Calculation (site is on green hosting → carbon rating).
- Assume Pages are HTML (URLs without Content-Type treated as HTML).
- Response Timeout (secs) (default 20 s).
- 5XX Response Retries (auto-retry count).

## 3.6 Spider > Preferences (thresholds used by filters)
- Page Title width: min/max characters (defaults 30 / 60) and min/max pixels (200 / 561).
- Meta Description width: min/max characters (70 / 155) and min/max pixels (400 / 985). (Desktop/mobile/tablet pixel presets for SERP snippet.)
- Links: High Internal Outlinks threshold (default 1,000), High External Outlinks threshold, High Crawl Depth threshold, Non-Descriptive Anchor Text list (other defaults not stated in fetched docs).
- Other: max URL length (115 chars), max H1 length (70), max H2 length (70), max image alt text length (100), max image size KB (100), Low Content word count threshold.

## 3.7 Content
- Content > Area — include/exclude HTML elements, classes, IDs for word count, near-duplicates, spelling & grammar (default: `<body>` minus `<nav>` and `<footer>`); adjustable post-crawl.
- Content > Duplicates — exact duplicates (hash, on by default); Enable Near Duplicates (MinHash, default similarity threshold 90%, adjustable); Only Check Indexable Pages for Duplicates (default on); needs crawl analysis.
- Content > Spelling & Grammar — enable spelling and/or grammar; auto language from `lang` attribute or manual; ~40 languages; Grammar Rules toggles; Ignore list (per crawl); Dictionary (persistent); re-runnable post-crawl.
- Content > Embeddings — enable embedding functionality using an AI provider prompt (OpenAI, Gemini, Ollama; needs Store HTML); Semantic Similarity and Low Relevance toggles (populate Content tab filters after crawl analysis); Embedding Rules (URL patterns limiting where semantic matches are sought, e.g. staging vs live for redirect mapping).

## 3.8 Robots.txt
- Mode: Respect robots.txt (default) / Ignore robots.txt (not even downloaded) / Ignore robots.txt but report status.
- Show Internal URLs Blocked by Robots.txt (default on; status code 0 "Blocked by Robots.txt", "matched robots.txt line" column).
- Show External URLs Blocked by Robots.txt (default off).
- Custom Robots — download, edit and test robots.txt per subdomain, overriding live file for the crawl; uses configured robots user-agent.
- Behaviour: follows only one UA group (SF UA → Googlebot → `*`); wildcard `*` / `$` matching; longest matching allow beats disallow; blank robots UA → only `*` rules.

## 3.9 URL Rewriting
- Remove Parameters (list of parameter names, e.g. `sid`, `utm_source`).
- Regex Replace (ordered regex → replacement rules; e.g. http→https, strip query, strip `#…`, append parameters).
- Options / Additional Settings: Lowercase Discovered URLs; Percent Encoding Mode (uppercase vs lowercase hex).
- Test box to preview a rewrite. Not applied to start URL / list-mode URLs.

## 3.10 CDNs
- List of domains (optionally domain + subfolder) to treat as internal.

## 3.11 Include / Exclude
- Include — regex list; only matching URLs crawled (matched against URL-encoded address; start page must link to a match).
- Exclude — regex list; matching URLs are not crawled at all; applied to newly discovered + pending queue (not start URLs); supports `\Q…\E` literal quoting.

## 3.12 Speed
- Max Threads (default 5).
- Max URI/s (requests per second throttle).

## 3.13 User-Agent
- Presets: Screaming Frog SEO Spider (default), Googlebot (desktop/smartphone), Bingbot, various browsers, etc.
- Custom: HTTP Request User-Agent string + separate Robots User-Agent (which robots.txt group to obey).

## 3.14 HTTP Header
- Arbitrary custom request headers (Accept-Language, Cookie, Referer, any name/value). UA set separately.

## 3.15 Custom
- Custom > Search — up to 100 filters; each: name, Contains / Does Not Contain, Text / Regex, query, scope (HTML, page text, specific element, XPath, etc.); raw or rendered HTML; Java regex; results in Custom Search tab (occurrence counts).
- Custom > Extraction — up to 100 extractors (max 1,000 extracted values total); modes XPath, CSS Path (+ optional attribute), Regex; output Extract HTML Element / Extract Inner HTML / Extract Text / Function Value (e.g. `count(//h1)`); visual point-and-click extractor in built-in browser with preview; runs on internal 2XX HTML (raw or rendered). Regex dot matches newline.
- Custom > Link Positions — ordered list of link-path (XPath) substrings → position labels (Head, Nav, Header, Sidebar, Footer, Content…); "Content" = `/` catch-all last; can disable link position classification.
- Custom > JavaScript — snippets run on each internal 200 page (not PDFs) in JS mode; types: Extraction (returns values → columns; stops page loading) and Action (e.g. scroll, mouseover; needs timeout); content-type filter per snippet; library of presets (sentiment/intent/language via LLM, alt-text generation, infinite scroll, embeddings, download images…); user library import/export as JSON; API `seoSpider.data()`, `.error()`, `.saveText(text, path, append)`, `.saveUrls(urls, dir)`, `.loadScript(src)`; access to Chrome Console Utilities API; Action snippets run before Extraction snippets.

## 3.16 API Access
- Google Analytics 4 — OAuth; account / property / data stream; up to 65 metrics (defaults: Sessions, Engaged Sessions, Engagement Rate, Views, Conversions, Event Count, Total Revenue); dimension per metric (page path vs landing page); filters tab (e.g. channel grouping = Organic Search); date range; Match Trailing & Non-Trailing Slash URLs; Match Uppercase & Lowercase URLs; Limit Max Results (default top 100k by sessions); Crawl New URLs Discovered in GA. Populates Analytics tab (filters: Sessions Above 0, Bounce Rate Above 70%, No GA Data, Non-Indexable with GA Data, Orphan URLs). (CLI also supports legacy Universal Analytics.)
- Google Search Console — OAuth; property; Search Analytics (Clicks, Impressions, CTR, Position; default last 30 days; adjustable date range, dimensions and other settings); Crawl New URLs Discovered in GSC; URL Inspection API (Enable URL Inspection, 2,000 URLs/property/day, Ignore Non-Indexable URLs for URL Inspection, Use Multiple Properties) returning Summary, Coverage, Last Crawl, Crawled As, Crawl Allowed, Page Fetch, Indexing Allowed, User-Declared Canonical, Google-Selected Canonical, Mobile Usability (+ issues), AMP Results (+ issues), Rich Results (types, errors, warnings), Referring Pages, Sitemaps.
- PageSpeed Insights — source Remote (PSI API, key, includes CrUX; 25k/day, 60 per 100 s) or Local (Lighthouse on the machine; works behind auth; no CrUX); device (mobile/desktop); metric groups: Overview (total size/time savings, requests, page size, per-type size & count for HTML/Image/CSS/JS/Font/Media/Other/Third-party), CrUX page & origin (CWV assessment, FCP, LCP, CLS, INP, TTFB + categories), Lighthouse lab (Performance Score, FCP, Speed Index, LCP, TTI, Max Potential FID, TBT, CLS + scores), Insights, Diagnostics, Mobile Friendly; PSI Status / PSI Error columns.
- Majestic — Open Apps token; Fresh / Historic index; metrics at URL / subdomain / domain level → Link Metrics tab.
- Ahrefs — OAuth "Sign in with Ahrefs" (API v3, integration units); metrics at URL / subdomain / domain → Link Metrics tab.
- Moz — access token (free or paid); metrics at URL / subdomain / domain → Link Metrics tab.
- AI > OpenAI — API key; up to 100 prompts; model category (Chat, Moderation, Embeddings), model, content type filter, input data (page text, HTML, custom extraction…), custom prompt; prompt tester; prompt library (presets + user, import/export). Results in AI tab + Internal tab. Can generate images / text-to-speech audio.
- AI > Gemini — API key; prompts (Gemini chat or Embeddings); Advanced: max requests per minute per model.
- AI > Ollama — local server URL (default `http://localhost:11434`); chat completion or embeddings models.
- AI > Anthropic — API key; prompts with Claude models.

## 3.17 Authentication
- Standards Based — Basic & Digest auth: auto-prompt during crawl or pre-entered URL + username + password.
- Forms Based — log in via built-in Chromium browser; cookies used for crawl (warning: crawler clicks every link, incl. logout/delete).
- Profiles — export `.seospiderauthconfig` (AES-256-GCM encrypted) for scheduling / CLI.

## 3.18 Segments
- Rule-based segments on any crawl data (incl. GA/GSC/post-crawl data), ordered precedence, can reference other segments; colour labels column in every tab; segment bar in Issues tab; Segments right-hand tab; used for visualisation colouring, per-segment XML sitemaps (+ index), per-segment Looker Studio sheets. Database mode only.

## 3.19 Crawl Analysis
- Post-crawl calculations (Configuration > Crawl Analysis). Confirmed in docs: Link Score (0–100 internal PageRank-like), Sitemaps filters, Orphan URLs (GA/GSC/Sitemap), Near Duplicates, Semantically Similar / Low Relevance Content. Likely also (list shown only as screenshot in docs, unverified): Canonicals Unlinked / Non-Indexable Canonical, Pagination Unlinked / Non-200 / Loop / Sequence Error, Hreflang return-link checks, Links "Non-Indexable Page Inlinks Only". Each item toggleable; "Auto Analyse At End of Crawl"; manual "Crawl Analysis > Start".

## 3.20 Compare config (Compare mode)
- Config > Compare — choose extra elements for change detection (Indexability, Page Titles, Meta Description, H1, Word Count, Crawl Depth, Inlinks, Unique Inlinks, Internal/External Outlinks (+ unique), Structured Data Unique Types, Content similarity threshold), URL Mapping (regex mapping of previous→current URLs, e.g. staging vs live) [URL Mapping unverified — not in fetched docs].

## 3.21 Configuration profiles
- Save Current Configuration As Default; Save As / Load / Load Recent profile (`.seospiderconfig`); Clear Default Configuration.

## 3.22 System settings (File > Settings)
- User Interface — Light / Dark theme, accent colour.
- Language — English, Spanish, German, French, Italian.
- Proxy — one HTTP/HTTPS proxy with credentials (restart required, no exceptions).
- Storage Mode — Database (default, SSD, auto-save, required for compare/change detection/segments/MCP) / Memory (RAM).
- Memory Allocation — JVM heap (default 2 GB on 64-bit).
- Crawl Retention — auto-delete old crawls after a period; lock projects/crawls.
- Trusted Certificates — folder of X.509 certs (.crt/.pem/.cer/.der) for MITM proxies; "Discover" issuer.
- Notifications — email via Outlook / Gmail / custom SMTP; Email on Crawl Complete (all crawls) or per scheduled task (with auto-compare changes + export attachments, zipped).
- MCP Server — run SEO Spider as MCP server (STDIO or Streamable HTTP at `http://localhost:11435/mcp`); Node.js tools (run script, npm install) and filesystem tools; configurable working directory. Tools: sf_list_crawls, sf_load_crawl, sf_export_crawl, sf_crawl, sf_pause_crawl, sf_resume_crawl, sf_clear_crawl, sf_crawl_progress, sf_generate_report, sf_generate_bulk_export, sf_bulk_export_page_content (NDJSON), sf_export_seo_element_urls (NDJSON), sf_export_embeddings, sf_get_url_screenshot, sf_url_info, sf_url_content, sf_url_links, sf_open_url_in_browser, sf_list_available_reports, sf_list_available_bulk_exports, sf_list_available_filters_for_seo_element, sf_list_available_data_fields_for_seo_element_and_filter, sf_run_node_js_script, sf_npm_install, sf_read_text_file, sf_write_text_file, sf_list_allowed_base_directory, sf_list_directories, sf_create_directory.
- Auto Updates check (Help > Debug).

---

# Part 4 — Modes (Mode menu)

- **Spider** (default) — crawl a website from a start URL, following links; classify URLs into tabs & filters.
- **List** — crawl a supplied list of URLs (paste, or upload .txt / .xls / .xlsx / .csv / .xml sitemap; any `http(s)://` string extracted). Crawl depth set to 0 and robots.txt ignored by default; "Export" button keeps original upload order incl. duplicates. Typical use: migrations with Always Follow Redirects / Canonicals.
- **SERP** — no crawling; upload URL / Title / Description (.txt, .csv, Excel) to compute character lengths and pixel widths (round-trip with SERP Summary report).
- **Compare** — compare two database-stored crawls; per tab/filter Current vs Previous with Added / New / Removed / Missing columns and filters; change detection tab (config > Compare); URL mapping; comparison file saved in File > Crawls. Also launchable via File > Crawls > Select To Compare.
- **APIs** — upload URLs and fetch only API data (GA, GSC, PSI, Majestic, Ahrefs, Moz) without crawling.

Related crawl-management features:
- Start / Pause / Resume / Clear crawl; re-spider selected URLs; remove URLs.
- File > Crawls (database mode): open, rename, project folders, duplicate, export, delete, lock, copy database ID, select to compare.
- Save / open / import / export crawls: `.dbseospider` (database) and `.seospider` (portable).
- Scheduling (File > Scheduling): one-off or interval; mode (Spider/List), URL, config profile, auth profile, APIs, headless; exports (Output Settings: local folder / Google Drive, timestamped or overwrite, CSV/Excel/Google Sheets, consolidate into one workbook; Spreadsheets: any tab/filter, bulk export, report; Local Files: save crawl, XML sitemap, image sitemap; Looker Studio time-series export; Presets; Notifications); auto-compare crawls; export/import `.task`; History with errors.
- CLI: `--crawl`, `--crawl-list`, `--load-crawl` (file or DB id), `--list-crawls`, `--crawl-comparison <id> <id>`, `--project-crawl-comparison`, `--config`, `--auth-config`, `--headless`, `--save-crawl`, `--output-folder`, `--overwrite`, `--project-name`, `--task-name`, `--timestamped-output`, `--export-tabs "tab:filter,..."`, `--bulk-export "submenu:export,..."`, `--save-report "submenu:report,..."`, `--export-custom-summary`, `--create-sitemap`, `--create-images-sitemap`, `--export-format csv|xls|xlsx|gsheet`, `--google-drive-account`, `--use-google-analytics`, `--use-google-analytics-4`, `--use-google-search-console`, `--use-pagespeed`, `--use-majestic`, `--use-mozscape`, `--use-ahrefs`, `--email-on-complete`, `--help [export-tabs|bulk-export|save-report|export-custom-summary]`.
- UI: draggable/hideable tabs and columns, Configure Tabs/Columns, Focus Mode (hide tabs not relevant to config), resizable panes, search box (text/regex, predefined filters incl. "does not match regex", AND/OR rules, column selection, case-sensitive, syntax shown), search in lower tabs and View Source.

---

# Part 5 — Reports, exports and other outputs

## 5.1 Exports
- Main-window export — export current tab + filter view (respects active filter/search).
- Lower-window export — right-click or Export button: URL Details, Inlinks, Outlinks, Image Details, Resources, Duplicate Details, Structured Data Details, Spelling & Grammar Details, Crawl Path Report; multi-select URLs for bulk.
- Formats — CSV, Excel 97-2004 (.xls), Excel Workbook (.xlsx), Google Sheets (via Google Drive OAuth; 5M-cell limit).
- Multi-Export — pick any tabs, bulk exports and reports in one go; save as presets (UI, scheduling, CLI); also runs Looker Studio export.
- Export for Looker Studio — custom crawl-overview summary row appended to a Google Sheet per run (time series; per-segment sheets).

## 5.2 Bulk Export menu
- Queued URLs.
- Links: All Inlinks; All Outlinks; All Anchor Text; External Links; Internal Nofollow Outlinks; Internal Outlinks With No Anchor Text; Non-Descriptive Anchor Text In Internal Outlinks; Follow & Nofollow Internal Inlinks To Page; Internal Nofollow Inlinks Only; Outlinks to Localhost. (Also inlinks by status: e.g. Response Codes > Internal & External > Client Error (4xx) Inlinks, Success/Redirection/Server Error inlinks, No Response inlinks, Blocked by robots.txt inlinks.)
- Web: Screenshots; Archived Website; All Page Source (original / rendered); All Page Text (.txt per page); All PDF Documents; All PDF Content (.txt); All HTTP Request Headers; All HTTP Response Headers; All Cookies.
- Path Type (absolute / protocol-relative / root-relative / path-relative links with sources).
- Security (links to URLs in each Security filter, e.g. Unsafe Cross-Origin Links, Mixed Content).
- Response Codes (inlinks to each response-code filter, internal & external).
- Content (e.g. Near Duplicates with all duplicate pairs, Exact Duplicates, Spelling/Grammar errors).
- Images (e.g. images missing alt text with source pages, all image alt text).
- Canonicals (links to URLs in each Canonicals filter).
- Directives (links to URLs in each Directives filter).
- JavaScript (e.g. Pages With JavaScript Issues / Blocked Resources).
- AMP (links to URLs in each AMP filter).
- Structured Data (per filter; RDF triples format: subject, predicate, object).
- Sitemaps (per Sitemaps filter, e.g. XML Sitemaps containing non-indexable URLs).
- Custom Search (per search filter).
- Custom Extraction (per extractor).
- URL Inspection: Rich Results (types, validity, severity, issue types); Referring Pages (up to 5 per URL); Sitemaps (sitemaps each URL was found in).
- Accessibility: All Violations; violations by WCAG level (issue, guideline, impact, location).
- Issues: All (each issue + "inlinks" variant as separate sheet in a folder).
- AI: Images; Text to Speech Audio.

## 5.3 Reports menu
- Crawl Overview — totals per tab/filter, URLs encountered/blocked/crawled, content types, response codes ("total URI description").
- Issues Overview / Segments Overview (summary of Issues tab and per-segment issues). [unverified — not in fetched docs]
- Redirects: All Redirects; Redirect Chains (2+ hops, loops, chain type HTTP/JS/meta refresh/canonical); Redirect & Canonical Chains; Redirects to Errors (to blocked, no response, 4XX, 5XX).
- Canonicals: Canonical Chains; Non-Indexable Canonicals (incl. "unlinked" column).
- Pagination: Non-200 Pagination URLs; Unlinked Pagination URLs.
- Hreflang: All Hreflang URLs; Non-200 Hreflang URLs; Unlinked Hreflang URLs; Missing Return Links; Inconsistent Language & Region Return Links; Non Canonical Return Links; Noindex Return Links.
- Insecure Content (HTTPS pages with HTTP links/resources).
- SERP Summary (URL, title, description, lengths, pixel widths; re-uploadable in SERP mode).
- Orphan Pages (URLs from GA / GSC / Sitemap not found in crawl, with source column).
- Structured Data: Validation Errors & Warnings Summary; Validation Errors & Warnings (per URL: property, format, severity, validation type, message); Google Rich Results Features Summary; Google Rich Results Features (URL × feature matrix).
- PageSpeed: PageSpeed Opportunities Summary (unique opportunities, URLs affected, avg/total savings); CSS Coverage Summary; JavaScript Coverage Summary; per-opportunity/diagnostic exports of source pages + resources.
- JavaScript: Chrome Console Log Summary (aggregated JS errors/issues, URLs affected, sample URL).
- Mobile: per-filter exports with Lighthouse details.
- Accessibility: Accessibility Violations Summary (URLs per violation, guideline, impact, priority, %, sample URL).
- HTTP Headers: HTTP Header Summary (unique response headers × URL count).
- Cookies: Cookie Summary (unique cookies by name/domain/expiry/secure/HttpOnly × URL count).
- Crawl Path Report (right-click export: shortest discovery path).

## 5.4 Sitemaps menu (generation)
- XML Sitemap — include HTML 200 pages; optional noindex, canonicalised, paginated, PDFs; lastmod (server response or custom date); priority (by level); changefreq (from Last-Modified or level); include images (incl. CDN/external images; min inlinks threshold to skip logos); auto split at 49,999 URLs + sitemap index; per-segment sitemaps.
- Images Sitemap — only pages with images, images with 200.

## 5.5 Visualisations menu
- Crawl visualisations: Force-Directed Crawl Diagram; 3D Force-Directed Crawl Diagram (up to 100k URLs, opens in browser); Crawl Tree Graph (left-right / top-down). Shortest-path tree; 10k node limit per view with focus/explore; node size & colour by metrics (unique inlinks, word count, GA sessions, GSC clicks, Link Score, Moz PA…), response codes or segments; indexable = green, non-indexable = red.
- Directory tree visualisations: Force-Directed Directory Tree Diagram; 3D Force-Directed Directory Tree Diagram; Directory Tree Graph.
- Word clouds: Inlink Anchor Text Word Cloud; Body Text Word Cloud (needs Store HTML).
- Content Cluster Diagram — 2D embedding clusters (up to 10k pages; sampling, dimension reduction, cluster count, colour by segment).
- Export visualisations as SVG.

## 5.6 Other analysis features
- Link Score (post-crawl internal PageRank-like 0–100).
- Carbon footprint / rating per page (CO2 per page load + rating; Green hosting option) [rating scale unverified] — feeds Validation "High Carbon Rating".
- Readability (Flesch Reading Ease, avg words per sentence).
- N-grams (1–6 grams) from stored HTML.
- Semantic search & semantic similarity via embeddings.
- Robots.txt tester (custom robots).
- SERP snippet emulator with editing.

---

# Appendix — Columns per main-window tab (from /user-guide/tabs/)

- **Internal**: Address; Content; Status Code; Status; Indexability; Indexability Status; Title 1; Title 1 Length; Title 1 Pixel Width; Meta Description 1; Meta Description Length 1; Meta Description Pixel Width; Meta Keyword 1; Meta Keywords Length; h1; h1; h2; h2; Meta Robots 1; X-Robots-Tag 1; Meta Refresh 1; Canonical Link Element; rel=“next” 1; rel=“prev” 1; HTTP rel=“next” 1; HTTP rel=“prev” 1; Size; Transferred; Total Transferred; Word Count; Text Ratio; Crawl Depth; Folder Depth; Link Score; Inlinks; Unique Inlinks; Unique JS Inlinks; % of Total; Outlinks; Unique Outlinks; Unique JS Outlinks; External Outlinks; Unique External Outlinks; Unique External JS Outlinks; Closest Similarity Match; No. Near Duplicates; Spelling Errors; Grammar Errors; Language; Hash; Response Time; Last-Modified; Redirect URI; Redirect Type; HTTP Version; URL Encoded Address; Title 2, meta description 2, h1-2, h2-2 etc
- **External**: Address; Content; Status Code; Status; Crawl Depth; Inlinks
- **Security**: Address; Content; Status Code; Status; Indexability; Indexability Status; Canonical Link Element 1/2 etc; Meta Robots 1/2 etc; X-Robots-Tag 1/2 etc
- **Response Codes**: Address; Content; Status Code; Status; Indexability; Indexability Status; Inlinks; Response Time; Redirect URL; Redirect Type
- **URL**: Address; Content; Status Code; Status; Indexability; Indexability Status; Hash; Length; Canonical 1; URL Encoded Address
- **Page titles**: Address; Occurrences; Title 1/2; Title 1/2 length; Indexability; Indexability Status
- **Meta description**: Address; Occurrences; Meta Description 1/2; Meta Description 1/2 length; Indexability; Indexability Status
- **Meta keywords**: Address; Occurrences; Meta Keyword 1/2; Meta Keyword 1/2 length; Indexability; Indexability Status
- **h1**: Address; Occurrences; h1-1/2; h1-length-1/2; Indexability; Indexability Status
- **h2**: Address; Occurrences; h2-1/2; h2-length-1/2; Indexability; Indexability Status
- **Content**: Address; Word Count; Average Words Per Sentence; Flesch Reading Ease Score; Readability; Closest Similarity Match; No. Near Duplicates; Total Language Errors; Spelling Errors; Grammar Errors; Language; Hash; Indexability; Indexability Status
- **Images**: Address; Content; Size; Indexability; Indexability Status
- **Canonicals**: Address; Occurrences; Indexability; Indexability Status; Canonical Link Element 1/2 etc; HTTP Canonical 1/2 etc; Meta Robots 1/2 etc; X-Robots-Tag 1/2 etc; rel=“next” and rel=“prev”
- **Pagination**: Address; Occurrences; Indexability; Indexability Status; rel=“next”; rel=“prev”; Canonical Link Element 1/2 etc; HTTP Canonical 1/2 etc; Meta Robots 1/2 etc; X-Robots-Tag 1/2 etc
- **Directives**: Address; Meta Robots 1/2 etc; X-Robots-Tag 1/2 etc
- **hreflang**: Address; Title 1/2 etc; Occurrences; HTML hreflang 1/2 etc; HTML hreflang 1/2 URL etc; HTTP hreflang 1/2 etc; HTTP hreflang 1/2 URL etc; Sitemap hreflang 1/2 etc; Sitemap hreflang 1/2 URL etc
- **JavaScript**: Address; Status Code; Status; HTML Word Count; Rendered HTML Word Count; Word Count Change; JS Word Count %; HTML Title; Rendered HTML Title; HTML Meta Description; Rendered HTML Meta Description; HTML H1; Rendered HTML H1; HTML Canonical; Rendered HTML Canonical; HTML Meta Robots; Rendered HTML Meta Robots; Unique Inlinks; Unique JS Inlinks; Unique Outlinks; Unique JS Outlinks; Unique External Outlinks; Unique External JS Outlinks
- **Links**: Address; Indexability; Indexability Status; Crawl Depth; Link Score; Unique Inlinks; Unique JS Inlinks; % of Total; Outlinks; Unique Outlinks; Unique JS Outlinks; External Outlinks; Unique External Outlinks; Unique External JS Outlinks
- **AMP**: Address; Occurrences; Indexability; Indexability Status; Title 1; Title 1 Length; Title 1 Pixel Width; h1; h1; Size; Word Count; Text Ratio; Crawl Depth; Response Time
- **Structured data**: Address; Errors; Warnings; Total Types; Unique Types; Type 1; Type 2 etc
- **Sitemaps**: Address; Content Type; Status Code; Status; Indexability; Indexability Status
- **Mobile**: Address; PSI Status; PSI Error; Viewport; Tap Targets; Content Width; Font Display; Plugins; Mobile Alternate Link
- **Accessibility**: Address; Content Type; Status Code; Status; Indexability; Indexability Status; All Violations; Best Practice Violations; WCAG 2.0 A Violations; WCAG 2.0 AA Violations; WCAG 2.0 AAA Violations; WCAG 2.1 AA Violations; WCAG 2.2 AA Violations; PSI Status; PSI Error; Accessibility Score
- **Custom search**: Address; Content; Status Code; Status; Contains: [x]; Does Not Contain: [y]
- **Custom extraction**: Address; Content; Status Code; Status; [Extractor Name]
- **Custom JavaScript**: Address; Content Type; Status Code; Status; [Snippet Name]
- **Analytics**: Sessions; % New Sessions; New Users; Bounce Rate; Page Views Per Session; Avg Session Duration; Page Value; Goal Conversion Rate; Goal Completions All; Goal Value All
- **Search Console**: Clicks; Impressions; CTR; Position; Summary; Coverage; Last Crawl; Crawled As; Crawl Allowed; Page Fetch; Indexing Allowed; User-Declared Canonical; Google-Selected Canonical; Mobile Usability; Mobile Usability Issues; AMP Results; AMP Issues; Rich Results; Rich Results Types; Rich Results Types Errors; Rich Results Warnings
- **Validation**: Address; Content; Status Code; Status; Indexability; Indexability Status
- **Link Metrics**: Address; Status Code; Title 1; Exact URL; Exact URL (HTTP + HTTPS); Subdomain; Domain
- **AI**: Address; Content Type; Status Code; Status; Indexability; Indexability Status; [Prompt Name]
- **Change Detection**: Address; Indexability; Title 1; Meta Description 1; h1; Word Count; Crawl Depth; Inlinks; Unique Inlinks; Outlinks; Unique Outlinks; External Outlinks; Unique External Outlinks; Unique Types
