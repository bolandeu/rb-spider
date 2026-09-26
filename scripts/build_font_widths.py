"""Build src/rb_spider/data/arial_widths.json — glyph advance widths of Arial, for SERP pixel widths.

    uv run --with fonttools scripts/build_font_widths.py [path/to/Arial.ttf]

Google draws result titles and snippets in Arial; a title's width in pixels is the sum of its characters'
advances at the font size (thresholds.serp_title_font_px). The table keeps Latin, Cyrillic and common
punctuation: {"units_per_em": 2048, "widths": {"<codepoint>": advance}}. Rerun only to add characters.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont  # ty: ignore[unresolved-import] — a one-off tool: uv run --with fonttools

DEFAULT_FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
TARGET = Path(__file__).parent.parent / "src" / "rb_spider" / "data" / "arial_widths.json"
RANGES = [(0x20, 0x7E), (0xA0, 0x17F), (0x400, 0x45F), (0x2010, 0x2027), (0x2030, 0x203A), (0x20AC, 0x20BD),
          (0x2116, 0x2122)]  # fmt: skip


def main() -> None:
    font = TTFont(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FONT)
    cmap, metrics = font.getBestCmap(), font["hmtx"].metrics
    widths = {
        str(code): metrics[cmap[code]][0] for low, high in RANGES for code in range(low, high + 1) if code in cmap
    }
    data = {"font": "Arial", "units_per_em": font["head"].unitsPerEm, "widths": widths}
    TARGET.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{TARGET}: {len(widths)} characters")


if __name__ == "__main__":
    main()
