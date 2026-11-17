"""Baseline B1: GLiNER2 zero-shot entities plus rules (SPEC.md section 6).

GLiNER2 finds settlements in each paragraph without any training on this
task. Rules then assemble events: the sentence's keywords give the event
type, each settlement gives one event per type, and the General Staff date
rule gives the day. A paragraph with no event keyword produces nothing.
Model names and the confidence threshold come from config.yaml.
"""

from __future__ import annotations

import re
from typing import Any

from src.prelabel import CLAIM_SOURCE, SENTENCE_END, event_date, paragraph_spans, spans

SYSTEM = "B1"
LABELS = ["settlement", "military unit", "weapon or equipment", "date"]
# Sentence keywords, first match wins. Stems cover the inflected forms.
TYPE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("air_strike", re.compile(r"авіаудар|авіаційн\w+\s+удар|керован\w+\s+авіабомб", re.I)),
    ("shelling", re.compile(r"обстріл", re.I)),
    ("ground_assault", re.compile(r"атак|штурм|наступ|боєзіткн|вклинит|просунут", re.I)),
]


def load_model(models: dict[str, Any], source: str = "gsu") -> Any:
    """The GLiNER2 model for a source's language. Slow: loads weights from disk."""
    from gliner2 import GLiNER2

    return GLiNER2.from_pretrained(models["b1_gliner_uk" if source == "gsu" else "b1_gliner_en"])


def event_types(sentence: str) -> list[str]:
    """Event types a sentence's keywords point to; the first matching rule only."""
    return next(([kind] for kind, pattern in TYPE_RULES if pattern.search(sentence)), [])


def settlements(model: Any, paragraph: str, threshold: float) -> list[tuple[int, int, str]]:
    """(start, end, text) of each settlement GLiNER2 finds, in reading order."""
    found = model.extract_entities(
        paragraph, LABELS, threshold=threshold, include_spans=True, include_confidence=True
    )
    items = found.get("entities", {}).get("settlement", [])
    return sorted((e["start"], e["end"], e["text"]) for e in items)


def extract(
    model: Any, text: str, report_id: str, report_date: str, threshold: float
) -> list[dict[str, Any]]:
    """Events of one General Staff report, as dicts with offsets and no coordinates."""
    day = event_date(report_date)
    events: list[dict[str, Any]] = []
    for a, b in paragraph_spans(text):
        sentences = spans(text, a, b, SENTENCE_END)
        seen: set[tuple[str, str]] = set()
        for start, _end, name in settlements(model, text[a:b], threshold):
            s_start, s_end = next(((x, y) for x, y in sentences if x <= a + start < y), (a, b))
            for kind in event_types(text[s_start:s_end]) or event_types(text[a:b]):
                if (name, kind) in seen:
                    continue
                seen.add((name, kind))
                events.append(
                    {
                        "id": f"{report_id}:{SYSTEM}:{len(events)}",
                        "report_id": report_id,
                        "sector": "FULL",
                        "event_type": kind,
                        "epistemic_status": "ua_claimed",
                        "claim_source": CLAIM_SOURCE,
                        "actor": "RU",
                        "target": "UA",
                        "location_text": name,
                        "geo_precision": 2,
                        "event_date": day,
                        "quantity": None,
                        "evidence_start": s_start,
                        "evidence_end": s_end,
                        "system": SYSTEM,
                    }
                )
    return events
