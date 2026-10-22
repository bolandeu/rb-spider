"""HTML in any charset → UTF-8 bytes: selectolax reads bytes as UTF-8 only and ignores `<meta charset>`.

Kept free of heavy imports: it runs on every HTML response of a crawl.
"""

from __future__ import annotations

import codecs
import re

_HEADER_CHARSET = re.compile(r"charset\s*=\s*[\"']?([\w.:-]+)", re.I)
# <meta charset="…"> and <meta http-equiv="Content-Type" content="text/html; charset=…">, in the first bytes
_META_CHARSET = re.compile(rb"<meta[^>]+?charset\s*=\s*[\"']?\s*([\w.:-]+)", re.I)
_PRESCAN = 2048
# WHATWG: these labels mean windows-1252 in HTML
_LATIN = {"iso-8859-1", "iso8859-1", "latin1", "latin-1", "l1", "ascii", "us-ascii", "cp1252", "windows-1252"}
_BOMS = ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))


def _codec(label: str | None) -> str | None:
    """A Python codec name for a charset label, or None if it's unknown."""
    if not label:
        return None
    label = label.strip().lower()
    if label in _LATIN:
        return "cp1252"
    try:
        return codecs.lookup(label).name
    except LookupError:
        return None


def declared_charset(body: bytes, content_type: str | None) -> str | None:
    """The charset the response declares: BOM, then the Content-Type header, then `<meta>` (HTML's order)."""
    for bom, name in _BOMS:
        if body.startswith(bom):
            return name
    if content_type and (found := _HEADER_CHARSET.search(content_type)) and (name := _codec(found.group(1))):
        return name
    if found := _META_CHARSET.search(body[:_PRESCAN]):
        return _codec(found.group(1).decode("ascii", "ignore"))
    return None


def to_utf8(body: bytes, content_type: str | None = None) -> bytes:
    """The HTML as UTF-8 bytes: valid UTF-8 stays as is (a cp1251 text is never valid UTF-8, a wrong declaration
    is common), otherwise the declared charset, otherwise a guess from the bytes."""
    if not body:
        return body
    if body.startswith(codecs.BOM_UTF8):
        body = body[3:]
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        return body
    if (charset := declared_charset(body, content_type)) is not None:
        try:
            return body.decode(charset).encode("utf-8")
        except UnicodeDecodeError, LookupError:
            pass  # the declaration lies: guess below
    from charset_normalizer import from_bytes

    best = from_bytes(body).best()
    return str(best).encode("utf-8") if best is not None else body.decode("utf-8", "replace").encode("utf-8")
