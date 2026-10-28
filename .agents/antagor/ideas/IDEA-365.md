---
id: IDEA-365
title: 'Flaky test: test_proxy dying-proxy fallback failed once in CI'
created: '2026-10-27T20:07:46+00:00'
source_project: spider
source_path: /Users/bolandau/Work/tools/spider
status: new
for_path: /Users/bolandau/Work/tools/spider
---

tests/test_proxy.py::test_with_fallback_direct_a_dying_proxy_is_dropped_and_its_urls_fetched_again failed in the CI gate of 2026-10-27 19:04 (gate_logs/20261027T190433-73944): _proxy_errors returned ['http://127.0.0.1:45629/missing']; trace has 'ValueError: I/O operation on closed file' in crawl.proxy_failed_on. Passed on main before and after. Find the race; a flaky test stops releases.
