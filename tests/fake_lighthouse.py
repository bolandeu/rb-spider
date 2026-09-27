"""A stand-in for the `lighthouse` command in tests: prints a Lighthouse-shaped JSON report for the URL it gets.

An audit fails (score 0) on a page whose path ends with /lh/<audit id>; /lh/broken makes Lighthouse fail.
"""

import json
import sys

from rb_spider.core.issues import PAGESPEED

url = next(arg for arg in sys.argv[1:] if arg.startswith("http"))
last = url.rstrip("/").rsplit("/", 1)[-1]
if last == "broken":
    print("Runtime error encountered: Chrome crashed", file=sys.stderr)
    sys.exit(1)
audits: dict[str, dict] = {audit_id: {"score": 0 if last == audit_id else 1, "scoreDisplayMode": "metricSavings",
                     "displayValue": f"{audit_id} on {last}" if last == audit_id else None,
                     "details": {"items": [{"url": url + "/app.js", "wastedBytes": 1000}]} if last == audit_id else {}}
          for audit_id in [a[0] for a in PAGESPEED] + ["target-size"]}  # fmt: skip
audits["largest-contentful-paint"] = {"score": 0.8, "numericValue": 2500.0, "displayValue": "2.5 s"}
print(json.dumps({"lighthouseVersion": "13.5.0", "audits": audits,
                  "categories": {"performance": {"score": 0.5}, "accessibility": {"score": 0.9}}}))  # fmt: skip
