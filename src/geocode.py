"""Give events coordinates from the gazetteer. Used the same way for gold and predictions.

An event's place is looked up as written; among same-named places the one
nearest the town of the paragraph's front direction wins (src/gazetteer.py).
Events with no place, or a place the gazetteer cannot resolve, get no
coordinates. A place that is itself a front direction ("Покровському
напрямку") is geocoded to the direction's town (SPEC.md 2.2, precision 2).
No model is involved.
"""

from __future__ import annotations

from typing import Any

from src.gazetteer import (
    Gazetteer,
    direction_anchor,
    direction_place,
    paragraph_direction,
    resolve,
)
from src.prelabel import paragraph_spans


def paragraph_at(text: str, offset: int) -> str:
    """The paragraph of `text` that contains character `offset` ("" if none)."""
    return next((text[a:b] for a, b in paragraph_spans(text) if a <= offset < b), "")


def geocode(
    events: list[dict[str, Any]], text: str, gaz: Gazetteer, cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Copies of `events` with lat, lon, gazetteer_id and geocode_how filled in."""
    out = []
    for e in events:
        place, how = None, "no_place"
        if e.get("location_text"):
            direction = paragraph_direction(paragraph_at(text, e["evidence_start"]))
            near = direction_anchor(gaz, direction, cfg["direction_anchors"])
            how, place, _ = resolve(gaz, e["location_text"], near, cfg["max_anchor_km"])
            named = direction_place(gaz, e["location_text"], cfg["direction_anchors"])
            if named and "напрям" in e["location_text"] or named and place is None:
                how, place = "direction", named  # a direction is geocoded to its town
        out.append(
            {
                **e,
                "lat": place.lat if place else None,
                "lon": place.lon if place else None,
                "gazetteer_id": place.gazetteer_id if place else None,
                "geocode_how": how,
            }
        )
    return out
