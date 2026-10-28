---
id: IDEA-369
title: 'Split the long modules: core/issues.py, core/settings.py, core/crawl.py (over
  800 lines)'
created: '2026-10-28T07:06:43+00:00'
source_project: spider
source_path: /Users/bolandau/Work/tools/spider
status: new
for_path: /Users/bolandau/Work/tools/spider
---

Antagor's docstring gate refuses code files over 800 lines (docstring.max_file_lines). issues.py 1497, settings.py 1242, crawl.py 964 lines were over it before; SPIDER-004 attempt 1 was refused only for that. They are in [docstring] exclude of .agents/antagor/antagor.toml until split. Split each by meaning (one capability, one module), no behaviour change, then remove the exclude.
