"""Build src/rb_spider/data/schemaorg.json — the Schema.org vocabulary the structured data checks validate against.

    uv run scripts/build_schemaorg.py [schemaorg-current-https.jsonld]

Without a file it downloads the current release from schema.org. The output keeps only what validation
needs: each type's parents, each property's domains (the types it is defined on), superseded terms.
Rerun it when Schema.org publishes a release; commit the JSON (~150 KB).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://schema.org/version/latest/schemaorg-current-https.jsonld"
TARGET = Path(__file__).parent.parent / "src" / "rb_spider" / "data" / "schemaorg.json"


def _ids(value) -> list[str]:
    items = value if isinstance(value, list) else [value] if value else []
    return sorted(item["@id"].removeprefix("schema:") for item in items if item["@id"].startswith("schema:"))


def main() -> None:
    if len(sys.argv) > 1:
        raw = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(SOURCE) as response:
            raw = response.read().decode()
    graph = json.loads(raw)["@graph"]
    types: dict[str, list[str]] = {}
    properties: dict[str, list[str]] = {}
    superseded: list[str] = []
    for node in graph:
        name = node["@id"].removeprefix("schema:")
        kinds = node["@type"] if isinstance(node["@type"], list) else [node["@type"]]
        if "rdfs:Class" in kinds:
            types[name] = _ids(node.get("rdfs:subClassOf"))
        if "rdf:Property" in kinds:
            properties[name] = _ids(node.get("schema:domainIncludes"))
        if "schema:supersededBy" in node:
            superseded.append(name)
    data = {"source": SOURCE, "types": types, "properties": properties, "superseded": sorted(superseded)}
    TARGET.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{TARGET}: {len(types)} types, {len(properties)} properties, {len(superseded)} superseded")


if __name__ == "__main__":
    main()
