"""Text measures of a page — readability and the MinHash signature for near duplicates — pure functions.

Run in the parser workers with the page's own text (menus and footers aside, `crawl.content_exclude`).
datasketch (extra `rb-spider[near]`) is imported only when a signature is asked for.
"""

from __future__ import annotations

import base64
import hashlib
import re
from array import array
from collections.abc import Iterator

_WORD_CHARS = re.compile(r"\S*[^\W\d_]\S*")  # a whitespace-separated token with a letter in it
_EN_VOWEL_GROUPS = re.compile(rb"[aeiouy]+")
_EN_SILENT_E = re.compile(rb"[aeiouy][^aeiouy\W]+e\b")  # "make", "use" — not "the", "table", "free"
_RU_VOWELS = "аеёиоуыэюя"
_NOT_ASCII_LETTER = bytes(c for c in range(128) if not chr(c).isalpha())


def words(text: str) -> list[str]:
    """Tokens that have letters in them (numbers, symbols and bare URLs' punctuation aside), lower-case."""
    return [token.strip(".,;:!?…()[]«»\"'—-") for token in _WORD_CHARS.findall(text.lower())]


SAMPLE_CHARS = 5000


def readability(text: str) -> tuple[float, float] | None:
    """(Flesch Reading Ease, words per sentence), or None without letters.

    English text: Flesch's formula 206.835 − 1.015·ASL − 84.6·ASW. Russian (mostly Cyrillic letters):
    Oborneva's adaptation 206.835 − 1.3·ASL − 60.1·ASW — Russian words are longer, and the English
    coefficients would call almost any Russian page "very difficult". ASL — words per sentence,
    ASW — syllables per word (Russian: vowels; English: vowel groups less a silent e).

    It runs for every page of a crawl, so it counts with str.count / bytes.translate, never a loop or a
    regex match per word (English syllables aside), and only the first SAMPLE_CHARS characters (~700 words):
    ~0.05 ms a page. Words are whitespace-separated tokens; a sentence ends with . ! ? … before a space or at
    the end.
    """
    if len(text) > SAMPLE_CHARS:  # the averages settle long before the end of a long page
        text = text[: text.rfind(" ", 0, SAMPLE_CHARS) + 1 or SAMPLE_CHARS].rstrip()
    lower = " ".join(text.lower().split()) if "  " in text or "\n" in text else text.lower()
    count = lower.count(" ") + 1 if lower else 0  # single spaces between words: one count, not a split
    latin = len(lower.encode("ascii", "ignore").translate(None, _NOT_ASCII_LETTER))
    data = lower.encode()
    cyrillic = data.count(b"\xd0") + data.count(b"\xd1")  # the lead byte of every Cyrillic letter in UTF-8
    if not count or not latin + cyrillic:
        return None
    ends = sum(lower.count(f"{mark} ") for mark in ".!?…") + lower.endswith((".", "!", "?", "…"))
    sentences = max(ends, 1)
    if cyrillic > latin:
        syllables = sum(lower.count(vowel) for vowel in _RU_VOWELS)  # str.count of one character: the fastest
        score = 206.835 - 1.3 * count / sentences - 60.1 * syllables / count
    else:
        ascii_text = lower.encode("ascii", "ignore")
        groups = len(_EN_VOWEL_GROUPS.findall(ascii_text)) - len(_EN_SILENT_E.findall(ascii_text))
        score = 206.835 - 1.015 * count / sentences - 84.6 * max(groups, count) / count
    return round(score, 1), round(count / sentences, 1)


# --- near duplicates -------------------------------------------------------------------------

NUM_PERM = 128
SHINGLE = 3  # words per shingle


def _shingles(tokens: list[str]) -> set[bytes]:
    if len(tokens) < SHINGLE:
        return {" ".join(tokens).encode()} if tokens else set()
    return {" ".join(tokens[i : i + SHINGLE]).encode() for i in range(len(tokens) - SHINGLE + 1)}


def signature(text: str) -> str | None:
    """MinHash of the text's 3-word shingles: NUM_PERM 32-bit values, base64 (~700 characters). None — no words."""
    shingles = _shingles(words(text))
    if not shingles:
        return None
    from datasketch import MinHash  # extra `rb-spider[near]`: only crawls with collect.near_duplicates import it

    minhash = MinHash(num_perm=NUM_PERM)
    minhash.update_batch(list(shingles))
    return base64.b64encode(array("I", (int(v) & 0xFFFFFFFF for v in minhash.hashvalues)).tobytes()).decode()


def unpack(sig: str) -> array:
    values = array("I")
    values.frombytes(base64.b64decode(sig))
    return values


def similarity(a: array, b: array) -> float:
    """Estimated Jaccard similarity of two signatures: the share of equal positions."""
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def bands_for(threshold: float, num_perm: int = NUM_PERM) -> tuple[int, int]:
    """(bands, rows per band) for LSH: pages that agree on a whole band become candidates.

    A pair of similarity s becomes a candidate with probability 1 − (1 − s^r)^b; the curve's midpoint
    (1/b)^(1/r) is set a little under the threshold, so pairs just above it are rarely missed.
    """
    target = max(threshold - 0.1, 0.05)
    best = (num_perm, 1)
    for rows in range(1, num_perm + 1):
        bands = num_perm // rows
        if abs((1 / bands) ** (1 / rows) - target) < abs((1 / best[0]) ** (1 / best[1]) - target):
            best = (bands, rows)
    return best


def band_hashes(values: array, bands: int, rows: int) -> Iterator[tuple[int, int]]:
    """(band, a signed 64-bit hash of the band's values) — what candidate pages are grouped by in SQL."""
    for band in range(bands):
        chunk = values[band * rows : (band + 1) * rows].tobytes()
        yield band, int.from_bytes(hashlib.blake2b(chunk, digest_size=8).digest(), "little", signed=True)
