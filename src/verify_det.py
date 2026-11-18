"""Deterministic verification (pipeline step 3, system S2; SPEC.md 2.2 and 2.3).

No model. For each extracted event the code finds the evidence quote in the
text and computes the offsets. The event is rejected when the quote is not in
the text, when `location_text` is not inside the quote, or when `quantity` is
not inside the quote as digits or as a number word. Rejections are counted by
reason.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from src.prelabel import NUMBER, to_int

QUOTE_MISSING = "quote_missing"
LOCATION_NOT_IN_QUOTE = "location_not_in_quote"
QUANTITY_NOT_IN_QUOTE = "quantity_not_in_quote"
REASONS = (QUOTE_MISSING, LOCATION_NOT_IN_QUOTE, QUANTITY_NOT_IN_QUOTE)

QUOTES = "“”„‟«»`"
APOSTROPHES = "’ʼ‘"
DASHES = "‐‑‒–—―−"
# English number words of SPEC Appendix C (ISW reports); Ukrainian ones are in src/prelabel.py.
ENGLISH = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "dozen": 12,
}  # fmt: skip
DIGITS = re.compile(r"\d+(?:[ ,  ]\d{3})*")


def _fold(ch: str) -> str:
    if ch in QUOTES:
        return '"'
    if ch in APOSTROPHES:
        return "'"
    if ch in DASHES:
        return "-"
    return ch


def normalise(text: str) -> tuple[str, list[tuple[int, int]]]:
    """SPEC 2.3 form of `text`, and for each character of it the (start, end) it came from."""
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1  # a letter and its combining marks are composed together (NFC)
        chunk = unicodedata.normalize("NFC", text[i:j])
        if chunk.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                spans.append((i, j))
        else:
            for ch in chunk:
                out.append(_fold(ch))
                spans.append((i, j))
        i = j
    return "".join(out), spans


def find_quote(quote: str, text: str) -> tuple[int, int, bool] | None:
    """(start, end, ambiguous) of the first occurrence of `quote` in `text`, or None.

    Offsets index the original `text`, end exclusive. `ambiguous` is true when
    the normalised quote occurs more than once.
    """
    q = normalise(quote)[0].strip()
    norm, spans = normalise(text)
    at = norm.find(q) if q else -1
    if at < 0:
        return None
    return spans[at][0], spans[at + len(q) - 1][1], norm.find(q, at + 1) >= 0


def has_location(quote: str, location: str) -> bool:
    return normalise(location)[0].strip() in normalise(quote)[0]


def has_quantity(quote: str, quantity: int) -> bool:
    """SPEC 2.2: the number is in the quote as digits or as an Appendix C number word."""
    digits = {int(re.sub(r"\D", "", m)) for m in DIGITS.findall(quote)}
    ukrainian = {to_int(tok) for tok in re.findall(NUMBER, quote)}
    english = {ENGLISH.get(w.lower()) for w in re.findall(r"[A-Za-z]+", quote)}
    return quantity in digits | ukrainian | english


def check(event: dict[str, Any], text: str) -> tuple[dict[str, Any] | None, str | None]:
    """The event with code-computed offsets, or (None, reason) if it is rejected."""
    quote = event.get("evidence_quote") or ""
    found = find_quote(quote, text)
    if found is None:
        return None, QUOTE_MISSING
    if event.get("location_text") and not has_location(quote, event["location_text"]):
        return None, LOCATION_NOT_IN_QUOTE
    if event.get("quantity") is not None and not has_quantity(quote, event["quantity"]):
        return None, QUANTITY_NOT_IN_QUOTE
    start, end, ambiguous = found
    return {
        **event,
        "evidence_start": start,
        "evidence_end": end,
        "ambiguous_offset": ambiguous,
    }, None


def verify(events: list[dict[str, Any]], text: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Events that pass the checks, and the number rejected for each reason."""
    kept: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for e in events:
        record, reason = check(e, text)
        if record is None:
            rejected[reason or ""] += 1
        else:
            kept.append(record)
    return kept, rejected
