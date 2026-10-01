"""tables under the spider_ prefix, a PRIMARY KEY on every table, the links view as spider_links

The shared PostgreSQL holds every tool's tables in one `public` schema, so every spider object is named `spider_*`;
Directus needs a single-column PRIMARY KEY on every table. Tables without one (or with a composite one: frontier,
url_metrics — their key becomes UNIQUE) get a surrogate `id` — in SQLite an alias of the rowid, filled from it (pages and render_events keep their order and ids). SQLite can neither rename a constraint nor add a
primary key, so each table is rebuilt: create the new one, copy, drop the old (children first). The whole database is
rewritten once — it needs free disk space the size of the file.

SQLite only: PostgreSQL never ran 0001–0032 — a new one starts here from `migrations/pg_baseline.py`.

Revision ID: 0033
Revises: 0032
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

# the schema of 0033, literal (generated once from core/tables.py; later migrations change it, not this list)
CREATE = [
    "CREATE TABLE spider_projects ( id INTEGER NOT NULL, name VARCHAR NOT NULL, created_at DATETIME NOT NULL, CONSTRAINT spider_projects_pk PRIMARY KEY (id), CONSTRAINT spider_projects_name_uq UNIQUE (name) )",
    "CREATE TABLE spider_crawls ( id INTEGER NOT NULL, project_id INTEGER NOT NULL, start_url VARCHAR NOT NULL, status VARCHAR NOT NULL, started_at DATETIME NOT NULL, finished_at DATETIME, pages INTEGER DEFAULT '0' NOT NULL, settings JSON, pid INTEGER, CONSTRAINT spider_crawls_pk PRIMARY KEY (id), CONSTRAINT spider_crawls_project_id_fk FOREIGN KEY(project_id) REFERENCES spider_projects (id) ON DELETE CASCADE )",
    "CREATE TABLE spider_custom_values ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, kind VARCHAR NOT NULL, name VARCHAR NOT NULL, value VARCHAR, n INTEGER NOT NULL, CONSTRAINT spider_custom_values_pk PRIMARY KEY (id), CONSTRAINT spider_custom_values_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_custom_values_by_name ON spider_custom_values (crawl_id, kind, name)",
    "CREATE TABLE spider_frontier ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, depth INTEGER NOT NULL, check_only BOOLEAN NOT NULL, done BOOLEAN DEFAULT 0 NOT NULL, CONSTRAINT spider_frontier_pk PRIMARY KEY (id), CONSTRAINT spider_frontier_by_url UNIQUE (crawl_id, url), CONSTRAINT spider_frontier_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_frontier_pending ON spider_frontier (crawl_id, done)",
    "CREATE TABLE spider_issues ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, code VARCHAR NOT NULL, url VARCHAR NOT NULL, detail VARCHAR, CONSTRAINT spider_issues_pk PRIMARY KEY (id), CONSTRAINT spider_issues_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_issues_by_code ON spider_issues (crawl_id, code)",
    "CREATE TABLE spider_lighthouse_audits ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, strategy VARCHAR NOT NULL, audit VARCHAR NOT NULL, score FLOAT, value FLOAT, display VARCHAR, items VARCHAR, source VARCHAR, CONSTRAINT spider_lighthouse_audits_pk PRIMARY KEY (id), CONSTRAINT spider_lighthouse_audits_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_lighthouse_audits_by_url ON spider_lighthouse_audits (crawl_id, url)",
    "CREATE TABLE spider_link_rows ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, kind VARCHAR NOT NULL, internal BOOLEAN NOT NULL, anchor VARCHAR, alt VARCHAR, rel VARCHAR, nofollow BOOLEAN DEFAULT 0 NOT NULL, alt_attr BOOLEAN, sized BOOLEAN, fragment VARCHAR, hreflang VARCHAR, position VARCHAR, path VARCHAR, path_type VARCHAR, origin VARCHAR, CONSTRAINT spider_link_rows_pk PRIMARY KEY (id), CONSTRAINT spider_link_rows_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_link_rows_by_source ON spider_link_rows (crawl_id, source_id)",
    "CREATE INDEX spider_link_rows_by_target ON spider_link_rows (crawl_id, target_id)",
    "CREATE INDEX spider_link_rows_hreflang_by_source ON spider_link_rows (crawl_id, source_id) WHERE kind = 'hreflang'",
    "CREATE INDEX spider_link_rows_hreflang_by_target ON spider_link_rows (crawl_id, target_id) WHERE kind = 'hreflang'",
    "CREATE INDEX spider_link_rows_mobile ON spider_link_rows (crawl_id, source_id) WHERE kind = 'mobile_alternate'",
    "CREATE INDEX spider_link_rows_pagination ON spider_link_rows (crawl_id, source_id) WHERE kind IN ('next', 'prev')",
    "CREATE INDEX spider_link_rows_with_fragment ON spider_link_rows (crawl_id) WHERE fragment IS NOT NULL",
    "CREATE TABLE spider_near_duplicates ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url_a VARCHAR NOT NULL, url_b VARCHAR NOT NULL, similarity FLOAT NOT NULL, CONSTRAINT spider_near_duplicates_pk PRIMARY KEY (id), CONSTRAINT spider_near_duplicates_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_near_duplicates_by_a ON spider_near_duplicates (crawl_id, url_a)",
    "CREATE INDEX spider_near_duplicates_by_b ON spider_near_duplicates (crawl_id, url_b)",
    "CREATE TABLE spider_pages ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, status_code INTEGER NOT NULL, redirect_url VARCHAR, content_type VARCHAR, title VARCHAR, bytes INTEGER NOT NULL, depth INTEGER NOT NULL, fetched_at DATETIME NOT NULL, error VARCHAR, blocked VARCHAR, blocked_rule VARCHAR, refresh_url VARCHAR, refresh_kind VARCHAR, title_count INTEGER, title_outside_head INTEGER, meta_description VARCHAR, meta_description_count INTEGER, meta_description_outside_head INTEGER, meta_keywords VARCHAR, meta_keywords_count INTEGER, title_px INTEGER, description_px INTEGER, h1 VARCHAR, h1_count INTEGER, h1_from_alt BOOLEAN, h1_first_heading BOOLEAN, h2 VARCHAR, h2_count INTEGER, h2_sequential BOOLEAN, robots_directives VARCHAR, robots_outside_head INTEGER, canonical_url VARCHAR, canonical_count INTEGER, canonical_conflict BOOLEAN, canonical_outside_head INTEGER, canonical_invalid_attr BOOLEAN, canonical_relative BOOLEAN, canonical_fragment BOOLEAN, indexable BOOLEAN, indexability_status VARCHAR, content_md5 VARCHAR, word_count INTEGER, lorem_ipsum BOOLEAN, external BOOLEAN, parsed BOOLEAN, internal_outlinks INTEGER, external_outlinks INTEGER, internal_nofollow_outlinks INTEGER, uncrawlable_outlinks INTEGER, rendered BOOLEAN, raw_title VARCHAR, raw_meta_description VARCHAR, raw_h1 VARCHAR, raw_canonical VARCHAR, raw_directives VARCHAR, raw_word_count INTEGER, js_outlinks INTEGER, js_errors INTEGER, js_warnings INTEGER, blocked_resources INTEGER, ajax_meta_fragment BOOLEAN, hashbang_links INTEGER, screenshot VARCHAR, link_score INTEGER, image_width INTEGER, image_height INTEGER, response_ms INTEGER, last_modified VARCHAR, headers VARCHAR, inlinks INTEGER, unique_inlinks INTEGER, unique_outlinks INTEGER, anchor_ids VARCHAR, url_issues VARCHAR, hreflang_outside_head INTEGER, pagination VARCHAR, security_missing VARCHAR, sniffed_type VARCHAR, forms INTEGER, unsafe_blank_links INTEGER, protocol_relative INTEGER, head_tags INTEGER, body_tags INTEGER, body_before_html BOOLEAN, head_not_first BOOLEAN, invalid_head_element VARCHAR, viewport VARCHAR, plugins INTEGER, flesch FLOAT, words_per_sentence FLOAT, text_ratio FLOAT, minhash VARCHAR, sd_formats VARCHAR, sd_types VARCHAR, sd_parse_errors INTEGER, sd_errors INTEGER, sd_warnings INTEGER, sd_rich_errors INTEGER, sd_rich_warnings INTEGER, sd_messages VARCHAR, sd_features VARCHAR, CONSTRAINT spider_pages_pk PRIMARY KEY (id), CONSTRAINT spider_pages_by_url UNIQUE (crawl_id, url), CONSTRAINT spider_pages_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_pages_by_md5 ON spider_pages (crawl_id, content_md5)",
    "CREATE TABLE spider_render_events ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, kind VARCHAR NOT NULL, message VARCHAR, resource VARCHAR, CONSTRAINT spider_render_events_pk PRIMARY KEY (id), CONSTRAINT spider_render_events_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_render_events_by_url ON spider_render_events (crawl_id, url)",
    "CREATE TABLE spider_rendered_images ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, image VARCHAR NOT NULL, real_width INTEGER, real_height INTEGER, display_width INTEGER, display_height INTEGER, CONSTRAINT spider_rendered_images_pk PRIMARY KEY (id), CONSTRAINT spider_rendered_images_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_rendered_images_by_url ON spider_rendered_images (crawl_id, url)",
    "CREATE TABLE spider_sitemap_files ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, kind VARCHAR, bytes INTEGER, urls INTEGER, sitemaps INTEGER, error VARCHAR, CONSTRAINT spider_sitemap_files_pk PRIMARY KEY (id), CONSTRAINT spider_sitemap_files_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE TABLE spider_sitemap_urls ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, source VARCHAR NOT NULL, lastmod VARCHAR, CONSTRAINT spider_sitemap_urls_pk PRIMARY KEY (id), CONSTRAINT spider_sitemap_urls_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE INDEX spider_sitemap_urls_by_url ON spider_sitemap_urls (crawl_id, url)",
    "CREATE TABLE spider_url_metrics ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, source VARCHAR NOT NULL, name VARCHAR NOT NULL, value FLOAT, text VARCHAR, CONSTRAINT spider_url_metrics_pk PRIMARY KEY (id), CONSTRAINT spider_url_metrics_key UNIQUE (crawl_id, url, source, name), CONSTRAINT spider_url_metrics_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
    "CREATE TABLE spider_urls ( id INTEGER NOT NULL, crawl_id INTEGER NOT NULL, url VARCHAR NOT NULL, CONSTRAINT spider_urls_pk PRIMARY KEY (id), CONSTRAINT spider_urls_by_url UNIQUE (url, crawl_id), CONSTRAINT spider_urls_crawl_id_fk FOREIGN KEY(crawl_id) REFERENCES spider_crawls (id) ON DELETE CASCADE )",
]
COPY = [
    "INSERT INTO spider_projects (id, name, created_at) SELECT rowid, name, created_at FROM projects",
    "INSERT INTO spider_crawls (id, project_id, start_url, status, started_at, finished_at, pages, settings, pid) SELECT rowid, project_id, start_url, status, started_at, finished_at, pages, settings, pid FROM crawls",
    "INSERT INTO spider_custom_values (id, crawl_id, url, kind, name, value, n) SELECT rowid, crawl_id, url, kind, name, value, n FROM custom_values",
    "INSERT INTO spider_frontier (id, crawl_id, url, depth, check_only, done) SELECT rowid, crawl_id, url, depth, check_only, done FROM frontier",
    "INSERT INTO spider_issues (id, crawl_id, code, url, detail) SELECT rowid, crawl_id, code, url, detail FROM issues",
    "INSERT INTO spider_lighthouse_audits (id, crawl_id, url, strategy, audit, score, value, display, items, source) SELECT rowid, crawl_id, url, strategy, audit, score, value, display, items, source FROM lighthouse_audits",
    "INSERT INTO spider_link_rows (id, crawl_id, source_id, target_id, kind, internal, anchor, alt, rel, nofollow, alt_attr, sized, fragment, hreflang, position, path, path_type, origin) SELECT rowid, crawl_id, source_id, target_id, kind, internal, anchor, alt, rel, nofollow, alt_attr, sized, fragment, hreflang, position, path, path_type, origin FROM link_rows",
    "INSERT INTO spider_near_duplicates (id, crawl_id, url_a, url_b, similarity) SELECT rowid, crawl_id, url_a, url_b, similarity FROM near_duplicates",
    "INSERT INTO spider_pages (id, crawl_id, url, status_code, redirect_url, content_type, title, bytes, depth, fetched_at, error, blocked, blocked_rule, refresh_url, refresh_kind, title_count, title_outside_head, meta_description, meta_description_count, meta_description_outside_head, meta_keywords, meta_keywords_count, title_px, description_px, h1, h1_count, h1_from_alt, h1_first_heading, h2, h2_count, h2_sequential, robots_directives, robots_outside_head, canonical_url, canonical_count, canonical_conflict, canonical_outside_head, canonical_invalid_attr, canonical_relative, canonical_fragment, indexable, indexability_status, content_md5, word_count, lorem_ipsum, external, parsed, internal_outlinks, external_outlinks, internal_nofollow_outlinks, uncrawlable_outlinks, rendered, raw_title, raw_meta_description, raw_h1, raw_canonical, raw_directives, raw_word_count, js_outlinks, js_errors, js_warnings, blocked_resources, ajax_meta_fragment, hashbang_links, screenshot, link_score, image_width, image_height, response_ms, last_modified, headers, inlinks, unique_inlinks, unique_outlinks, anchor_ids, url_issues, hreflang_outside_head, pagination, security_missing, sniffed_type, forms, unsafe_blank_links, protocol_relative, head_tags, body_tags, body_before_html, head_not_first, invalid_head_element, viewport, plugins, flesch, words_per_sentence, text_ratio, minhash, sd_formats, sd_types, sd_parse_errors, sd_errors, sd_warnings, sd_rich_errors, sd_rich_warnings, sd_messages, sd_features) SELECT rowid, crawl_id, url, status_code, redirect_url, content_type, title, bytes, depth, fetched_at, error, blocked, blocked_rule, refresh_url, refresh_kind, title_count, title_outside_head, meta_description, meta_description_count, meta_description_outside_head, meta_keywords, meta_keywords_count, title_px, description_px, h1, h1_count, h1_from_alt, h1_first_heading, h2, h2_count, h2_sequential, robots_directives, robots_outside_head, canonical_url, canonical_count, canonical_conflict, canonical_outside_head, canonical_invalid_attr, canonical_relative, canonical_fragment, indexable, indexability_status, content_md5, word_count, lorem_ipsum, external, parsed, internal_outlinks, external_outlinks, internal_nofollow_outlinks, uncrawlable_outlinks, rendered, raw_title, raw_meta_description, raw_h1, raw_canonical, raw_directives, raw_word_count, js_outlinks, js_errors, js_warnings, blocked_resources, ajax_meta_fragment, hashbang_links, screenshot, link_score, image_width, image_height, response_ms, last_modified, headers, inlinks, unique_inlinks, unique_outlinks, anchor_ids, url_issues, hreflang_outside_head, pagination, security_missing, sniffed_type, forms, unsafe_blank_links, protocol_relative, head_tags, body_tags, body_before_html, head_not_first, invalid_head_element, viewport, plugins, flesch, words_per_sentence, text_ratio, minhash, sd_formats, sd_types, sd_parse_errors, sd_errors, sd_warnings, sd_rich_errors, sd_rich_warnings, sd_messages, sd_features FROM pages",
    "INSERT INTO spider_render_events (id, crawl_id, url, kind, message, resource) SELECT rowid, crawl_id, url, kind, message, resource FROM render_events",
    "INSERT INTO spider_rendered_images (id, crawl_id, url, image, real_width, real_height, display_width, display_height) SELECT rowid, crawl_id, url, image, real_width, real_height, display_width, display_height FROM rendered_images",
    "INSERT INTO spider_sitemap_files (id, crawl_id, url, kind, bytes, urls, sitemaps, error) SELECT rowid, crawl_id, url, kind, bytes, urls, sitemaps, error FROM sitemap_files",
    "INSERT INTO spider_sitemap_urls (id, crawl_id, url, source, lastmod) SELECT rowid, crawl_id, url, source, lastmod FROM sitemap_urls",
    "INSERT INTO spider_url_metrics (id, crawl_id, url, source, name, value, text) SELECT rowid, crawl_id, url, source, name, value, text FROM url_metrics",
    "INSERT INTO spider_urls (id, crawl_id, url) SELECT id, crawl_id, url FROM urls",
]
DROP = [
    "DROP TABLE urls",
    "DROP TABLE url_metrics",
    "DROP TABLE sitemap_urls",
    "DROP TABLE sitemap_files",
    "DROP TABLE rendered_images",
    "DROP TABLE render_events",
    "DROP TABLE pages",
    "DROP TABLE near_duplicates",
    "DROP TABLE link_rows",
    "DROP TABLE lighthouse_audits",
    "DROP TABLE issues",
    "DROP TABLE frontier",
    "DROP TABLE custom_values",
    "DROP TABLE crawls",
    "DROP TABLE projects",
]
LINKS_VIEW = "CREATE VIEW spider_links AS SELECT l.crawl_id, s.url AS source, t.url AS target, l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized, l.fragment, l.hreflang, CASE WHEN l.kind = 'hyperlink' THEN coalesce(l.position, 'content') END AS position, l.path, CASE l.path_type WHEN 'a' THEN 'absolute' WHEN 'p' THEN 'protocol-relative' WHEN 'r' THEN 'root-relative' WHEN 'l' THEN 'relative' END AS path_type, CASE WHEN l.kind = 'hyperlink' THEN CASE l.origin WHEN 'r' THEN 'rendered' WHEN 'b' THEN 'html & rendered' ELSE 'html' END WHEN l.kind = 'image' AND l.origin = 'c' THEN 'css background' END AS origin FROM spider_link_rows l JOIN spider_urls s ON s.id = l.source_id JOIN spider_urls t ON t.id = l.target_id"


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS links")
    for statement in (*CREATE, *COPY, *DROP, LINKS_VIEW):  # parents are copied first, children dropped first
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("0033 is one-way: restore the database from a backup made before the upgrade")
