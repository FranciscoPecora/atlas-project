"""Baseline B0: regex patterns plus gazetteer lookup, no model (SPEC.md section 6).

For General Staff reports the patterns are those of src/prelabel.py: one
ground_assault per place named after an area or direction marker, and
direction-level clashes, air strikes and shelling where no place is named.
The gold key for these reports started from the same patterns, so B0 is
favoured on them (amendment A1); its score is an upper reference for rules,
not a fair baseline. ISW patterns are added when ISW reports are collected.
"""

from __future__ import annotations

from typing import Any

from src.prelabel import CLAIM_SOURCE, event_date, prefill_report

SYSTEM = "B0"


def extract(text: str, report_id: str, report_date: str) -> list[dict[str, Any]]:
    """Events of one General Staff report, as dicts with offsets and no coordinates."""
    day = event_date(report_date)
    return [
        {
            "id": f"{report_id}:{SYSTEM}:{i}",
            "report_id": report_id,
            "sector": "FULL",
            "event_type": p.event_type,
            "epistemic_status": "ua_claimed",
            "claim_source": CLAIM_SOURCE,
            "actor": "RU",
            "target": "UA",
            "location_text": p.location_text,
            "geo_precision": 2 if p.location_text else None,
            "event_date": day,
            "quantity": p.quantity,
            "evidence_start": p.start,
            "evidence_end": p.end,
            "system": SYSTEM,
        }
        for i, p in enumerate(prefill_report(text))
    ]
