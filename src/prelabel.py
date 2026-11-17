"""Rule-based pre-fill for General Staff (GSU) reports. No model, no network.

    uv run python -m src.prelabel data/text/gsu/2026-07-21.txt   # print the pre-fills

GSU direction paragraphs follow one pattern: "On the X direction the enemy
attacked N times in the areas of A, B and towards C." This finds every place
after an area/direction marker and proposes one ground_assault per place per
day (guideline section 1), with the sentence as evidence. Paragraphs that name
no place but report clashes, air strikes or shelling on a named direction get
one event per kind, located at the direction.

The annotator checks every pre-fill: keep, fix, delete, or add what it missed.
Pre-fills are proposals only. SPEC.md section 4 allows them on dev units; test
units need a SPEC amendment first (src/labels.py enforces this).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

VERSION = "prelabel-rules-v1"
CLAIM_SOURCE = "Ukrainian General Staff"

UPPER = "А-ЯІЇЄҐ"
WORD = rf"[{UPPER}][\w’'\-]*"
PLACE = re.compile(rf"{WORD}(?:\s+{WORD})*")
MARKER = re.compile(
    r"\b(?:у|в)\s+(?:район(?:і|ах)|напрям(?:ку|ках)|бік)"
    r"(?:\s+населен(?:ого|их)\s+пункт(?:у|ів))?\s+"
)
DIRECTION = re.compile(rf"^На\s+({WORD}(?:\s+(?:і|та)\s+{WORD})?\s+напрямк\w*)")
NEGATIVE = re.compile(r"\bне\s+(?:провод|виявлен)")
SENTENCE_END = re.compile(r"\.(?:\s+|$)")

# Count words seen in GSU reports, by stem (SPEC.md Appendix C stems, extended
# with the adverbs "двічі"/"тричі"). Longer stems first so "дванадцят" wins.
COUNT_STEMS: list[tuple[str, int]] = [
    ("дванадцят", 12), ("одинадцят", 11), ("тринадцят", 13), ("чотирнадцят", 14),
    ("п’ятнадцят", 15), ("п'ятнадцят", 15), ("шістнадцят", 16), ("сімнадцят", 17),
    ("вісімнадцят", 18), ("дев’ятнадцят", 19), ("двадцят", 20), ("тридцят", 30),
    ("двічі", 2), ("тричі", 3), ("один", 1), ("одн", 1), ("дв", 2), ("тр", 3), ("чотир", 4),
    ("п’ят", 5), ("п'ят", 5), ("шіст", 6), ("шест", 6), ("сім", 7), ("сем", 7),
    ("вісім", 8), ("восьм", 8), ("дев’ят", 9), ("дев'ят", 9), ("десят", 10),
]  # fmt: skip
_STEMS = "|".join(re.escape(s) for s, _ in COUNT_STEMS)
NUMBER = rf"(?<![\w’'])(\d[\d\s]*\d|\d|(?:{_STEMS})[а-яіїєґ’']*)"
ATTACK_COUNT = re.compile(
    rf"{NUMBER}\s+(?:раз\w*|атак\w*|штурм\w*|наступальн\w*|спроб\w*|боєзіткн\w*)"
)
ADVERB_COUNT = re.compile(r"\b(двічі|тричі)\b")
# Direction-level kinds for paragraphs that name no settlement.
KINDS: list[tuple[str, re.Pattern[str]]] = [
    ("ground_assault", re.compile(rf"{NUMBER}\s+(?:\w+\s+)?(?:штурм\w*|боєзіткн\w*)")),
    ("air_strike", re.compile(rf"{NUMBER}\s+(?:авіаційних\s+удар\w*|авіаудар\w*)")),
    ("shelling", re.compile(rf"{NUMBER}\s+обстріл\w*")),
]


@dataclass(frozen=True)
class Prefill:
    start: int  # offsets into the report text
    end: int
    event_type: str
    location_text: str | None
    quantity: int | None


def to_int(token: str) -> int | None:
    """Digits ("10 408" too) or a Ukrainian count word; None if not a count."""
    t = token.replace(" ", "")
    if t.isdigit():
        return int(t)
    low = token.lower()
    for stem, value in COUNT_STEMS:
        if low.startswith(stem):
            return value
    return None


def spans(text: str, start: int, end: int, sep: re.Pattern[str]) -> list[tuple[int, int]]:
    """Split text[start:end] on sep; offsets stay absolute; blank pieces dropped."""
    out, cur = [], start
    for m in sep.finditer(text, start, end):
        out.append((cur, m.start() + (1 if m.group(0).startswith(".") else 0)))
        cur = m.end()
    out.append((cur, end))
    return [(a, b) for a, b in out if text[a:b].strip()]


def trim(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink [start, end) so it neither starts nor ends with whitespace."""
    piece = text[start:end]
    return start + len(piece) - len(piece.lstrip()), end - len(piece) + len(piece.rstrip())


def paragraph_spans(text: str) -> list[tuple[int, int]]:
    return [trim(text, a, b) for a, b in spans(text, 0, len(text), re.compile(r"\n\s*\n"))]


def places(text: str, start: int, end: int) -> list[tuple[int, int, str]]:
    """Places named after an area/direction marker, up to the end of its sentence."""
    stop = SENTENCE_END.search(text, start, end)
    end = stop.start() if stop else end
    marks = list(MARKER.finditer(text, start, end))
    found: list[tuple[int, int, str]] = []
    for i, m in enumerate(marks):
        seg_end = marks[i + 1].start() if i + 1 < len(marks) else end
        for p in PLACE.finditer(text, m.end(), seg_end):
            found.append((p.start(), p.end(), p.group(0)))
    return found


def attack_count(paragraph: str) -> int | None:
    m = ATTACK_COUNT.search(paragraph) or ADVERB_COUNT.search(paragraph)
    return to_int(m.group(1)) if m else None


def paragraph_prefills(text: str, start: int, end: int) -> list[Prefill]:
    para = text[start:end]
    if NEGATIVE.search(para):
        return []
    sentences = spans(text, start, end, SENTENCE_END)
    located: list[Prefill] = []
    seen: set[str] = set()
    for s_start, s_end in sentences:
        for _, _, name in places(text, s_start, s_end):
            if name not in seen:
                seen.add(name)
                located.append(Prefill(s_start, s_end, "ground_assault", name, None))
    if located:
        if len(located) == 1:  # a count belongs to the place only when it is alone
            located[0] = Prefill(**{**located[0].__dict__, "quantity": attack_count(para)})
        return located
    direction = DIRECTION.match(para)
    if not direction:
        return []
    events = []
    first_sentence = sentences[0]
    for kind, pattern in KINDS:
        m = pattern.search(para)
        if m and (n := to_int(m.group(1))) is not None:
            s_start, s_end = next((a, b) for a, b in sentences if a <= start + m.start() < b)
            s_start = min(s_start, first_sentence[0])  # keep the direction name in the span
            events.append(Prefill(s_start, s_end, kind, direction.group(1), n))
    return events


def prefill_report(text: str) -> list[Prefill]:
    out: list[Prefill] = []
    for a, b in paragraph_spans(text):
        out += paragraph_prefills(text, a, b)
    return out


def event_date(report_date: str) -> str:
    """GSU 08:00 report: the default event date is the day before (SPEC.md section 1)."""
    return (date.fromisoformat(report_date) - timedelta(days=1)).isoformat()


def to_prediction(prefills: list[Prefill], data: dict[str, Any]) -> dict[str, Any]:
    """Label Studio prediction for one task; only pre-fills inside the task's text."""
    unit_start, text = data["unit_start"], data["text"]
    day = event_date(data["report_date"])
    result: list[dict[str, Any]] = []
    for i, p in enumerate(
        x for x in prefills if unit_start <= x.start and x.end <= unit_start + len(text)
    ):
        s, e = p.start - unit_start, p.end - unit_start
        fields: list[tuple[str, str, dict[str, Any]]] = [
            ("event", "labels", {"labels": ["Event"]}),
            ("event_type", "choices", {"choices": [p.event_type]}),
            ("epistemic_status", "choices", {"choices": ["ua_claimed"]}),
            ("actor", "choices", {"choices": ["RU"]}),
            ("target", "choices", {"choices": ["UA"]}),
            ("geo_precision", "choices", {"choices": ["2"]}),
            ("claim_source", "textarea", {"text": [CLAIM_SOURCE]}),
            ("event_date", "textarea", {"text": [day]}),
        ]
        if p.location_text:
            fields.append(("location_text", "textarea", {"text": [p.location_text]}))
        if p.quantity is not None:
            fields.append(("quantity", "number", {"number": p.quantity}))
        span = {"start": s, "end": e, "text": text[s:e]}
        for name, kind, value in fields:
            result.append(
                {
                    "id": f"p{i}",
                    "from_name": name,
                    "to_name": "text",
                    "type": kind,
                    "value": {**span, **value},
                }
            )
    return {"model_version": VERSION, "score": 0, "result": result}


def main(argv: list[str] | None = None) -> None:
    for p in argv if argv is not None else sys.argv[1:]:
        text = Path(p).read_text(encoding="utf-8")
        found = prefill_report(text)
        print(f"== {p}: {len(found)} pre-filled events")
        for f in found:
            q = "" if f.quantity is None else f" x{f.quantity}"
            print(f"  {f.event_type:15} {f.location_text}{q}")


if __name__ == "__main__":
    main()
