"""Give events coordinates from the gazetteer. Used the same way for gold and predictions.

Same-named places are decided by a fixed rule order, and the rule that decided
each event is logged in `geocode_rule`:

1. `unique`        the name matches one gazetteer row;
2. `oblast`        the paragraph names an oblast and one candidate lies in it;
3. `direction`     one candidate lies within `max_anchor_km` of the town the
                   paragraph's front direction is named after (DECISIONS.md,
                   17 Nov); candidates beyond it are never chosen;
4. `previous_day`  nearest to the previous day's located events on the same
                   direction (given only to S3);
5. `nearest_town`  nearest to the direction's town;
6. `population`    largest population, settlements before areas, when the
                   paragraph names no direction.

Rules 5 and 6 are weak. Only for those, and only when a `chooser` is given (S3),
one model call may pick one of the candidate rows; it never outputs coordinates
(`model`). A place that is itself a front direction ("Покровському напрямку") is
geocoded to the direction's town (SPEC.md 2.2, precision 2).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from eval.score import haversine_km
from src.gazetteer import (
    Gazetteer,
    Place,
    direction_place,
    paragraph_direction,
    stem,
)
from src.prelabel import paragraph_spans

# Oblast as a paragraph writes it -> the gazetteer's `oblast` value. Adjective
# stems ("Сумської області") and region nouns ("на Сумщині"). Fixed list: many
# village names also end in -щина (Яструбщина), so no pattern is used.
OBLAST_WORDS = {
    "сумськ": "Sumy", "сумщин": "Sumy", "харківськ": "Kharkiv", "харківщин": "Kharkiv",
    "донецьк": "Donetsk", "донеччин": "Donetsk", "луганськ": "Luhansk", "луганщин": "Luhansk",
    "запорізьк": "Zaporizhzhia", "запоріжжі": "Zaporizhzhia", "херсонськ": "Kherson",
    "херсонщин": "Kherson", "дніпропетровськ": "Dnipropetrovsk",
    "дніпропетровщин": "Dnipropetrovsk", "чернігівськ": "Chernihiv Oblast",
    "чернігівщин": "Chernihiv Oblast", "миколаївськ": "Mykolaiv", "миколаївщин": "Mykolaiv",
    "полтавськ": "Poltava", "полтавщин": "Poltava",
}  # fmt: skip
OBLAST_ADJ = re.compile(r"(\w+)\s+област\w*", re.IGNORECASE)
WEAK_RULES = ("nearest_town", "population")
Point = tuple[float, float]


def paragraph_at(text: str, offset: int | None) -> str:
    """The paragraph of `text` that contains character `offset` ("" if none)."""
    if offset is None:  # a quote that was not found in the text has no offsets
        return ""
    return next((text[a:b] for a, b in paragraph_spans(text) if a <= offset < b), "")


def paragraph_oblasts(paragraph: str) -> set[str]:
    """Gazetteer oblast names the paragraph mentions ("Сумської області", "на Харківщині")."""
    words = [m.group(1) for m in OBLAST_ADJ.finditer(paragraph)]
    words += re.findall(r"\w*щин\w*|\w*ччин\w*|Запоріжжі", paragraph)
    found = set()
    for w in words:
        low = w.lower()
        found |= {obl for key, obl in OBLAST_WORDS.items() if low.startswith(key)}
    return found


def same_direction(a: str | None, b: str | None) -> bool:
    return bool(a and b) and set(stem(a or "").split()) == set(stem(b or "").split())


def is_area(p: Place) -> bool:
    """An administrative area row (raion, hromada) rather than a settlement."""
    return not p.kind.startswith("PPL") and p.gazetteer_id.startswith("gn:")


def nearest(cands: list[Place], points: list[Point]) -> Place:
    """The candidate closest to any of `points` (ties: earlier candidate)."""
    return min(cands, key=lambda p: min(haversine_km(p.lat, p.lon, *q) for q in points))


def disambiguate(
    cands: list[Place],
    oblasts: set[str],
    town: Place | None,
    max_km: float,
    previous: list[Point],
) -> tuple[Place | None, str, list[Place]]:
    """(chosen row or None, deciding rule, candidates still in play) by the fixed rule order."""
    if not cands:
        return None, "no_match", []
    alone = len(cands) == 1
    in_oblast = [c for c in cands if c.oblast in oblasts]
    if in_oblast:
        cands = in_oblast
    if town is not None:
        cands = [c for c in cands if haversine_km(c.lat, c.lon, town.lat, town.lon) <= max_km]
        if not cands:
            return None, "too_far", []
    if len(cands) == 1:
        if alone:
            return cands[0], "unique", cands
        if len(in_oblast) == 1:
            return cands[0], "oblast", cands
        return cands[0], "direction", cands
    if previous:
        return nearest(cands, previous), "previous_day", cands
    if town is not None:
        return nearest(cands, [(town.lat, town.lon)]), "nearest_town", cands
    return min(cands, key=lambda p: (is_area(p), -p.population)), "population", cands


Chooser = Callable[[dict[str, Any], list[Place], Place | None], Place | None]


def geocode(
    events: list[dict[str, Any]],
    text: str,
    gaz: Gazetteer,
    cfg: dict[str, Any],
    previous: list[dict[str, Any]] | None = None,
    chooser: Chooser | None = None,
) -> list[dict[str, Any]]:
    """Copies of `events` with lat, lon, gazetteer_id, geocode_how and geocode_rule.

    `previous` is the previous day's geocoded events (each with `direction`);
    `chooser` is the optional model tie-break. Both are given only to S3.
    """
    out = []
    for e in events:
        place, how, rule = None, "no_place", "no_place"
        direction = None
        if e.get("location_text"):
            paragraph = paragraph_at(text, e.get("evidence_start"))
            direction = paragraph_direction(paragraph)
            town = direction_place(gaz, direction, cfg["direction_anchors"])
            how, cands = gaz.lookup(e["location_text"], limit=100_000)  # every namesake
            points = [
                (p["lat"], p["lon"]) for p in previous or []
                if p.get("lat") is not None and same_direction(p.get("direction"), direction)
            ]  # fmt: skip
            place, rule, left = disambiguate(
                cands, paragraph_oblasts(paragraph), town, cfg["max_anchor_km"], points
            )
            if rule in WEAK_RULES and chooser is not None and len(left) > 1:
                picked = chooser(e, left, town)
                if picked is not None:
                    place, rule = picked, "model"
            if rule == "too_far":
                how = "too_far"
            named = direction_place(gaz, e["location_text"], cfg["direction_anchors"])
            if named and ("напрям" in e["location_text"] or place is None):
                how, rule, place = "direction", "direction_name", named
        out.append(
            {
                **e,
                "lat": place.lat if place else None,
                "lon": place.lon if place else None,
                "gazetteer_id": place.gazetteer_id if place else None,
                "geocode_how": how,
                "geocode_rule": rule,
                "direction": direction,
            }
        )
    return out


class Choice(BaseModel):
    gazetteer_id: str | None = Field(
        description="The id of the candidate row the event happened at, or null if none fits"
    )


CHOOSER_TASK = (
    "A military report names a place that matches several rows of a gazetteer of "
    "Ukrainian settlements. Choose the row the report means, using only the quote, the "
    "front direction and the rows given. Answer with one of the listed ids, or null if "
    "none fits. Never invent an id."
)


def chooser_prompt(event: dict[str, Any], cands: list[Place], town: Place | None) -> str:
    lines = [
        f"Place as written: {event['location_text']}",
        f"Evidence quote: {event.get('evidence_quote', '')}",
        f"Front direction named after: {town.name if town else 'none'}",
        "Candidate rows:",
    ]
    for c in cands:
        km = f"{haversine_km(c.lat, c.lon, town.lat, town.lon):.0f} km" if town else "n/a"
        names = ", ".join(c.aliases[:4])
        lines.append(f"- id {c.gazetteer_id}: {c.name} ({names}); oblast {c.oblast or '?'}; "
                     f"population {c.population}; distance to that town {km}")  # fmt: skip
    return "\n".join(lines)


def model_chooser(client: Any, cfg: dict[str, Any], log: list[dict[str, Any]]) -> Chooser:
    """A Chooser that asks `models.geocode_disambiguation`; usage of every call goes to `log`."""

    def choose(event: dict[str, Any], cands: list[Place], town: Place | None) -> Place | None:
        response = client.beta.messages.parse(
            model=cfg["models"]["geocode_disambiguation"],
            max_tokens=4000,
            output_config={"effort": cfg["models"]["verifier_effort"]},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=CHOOSER_TASK,
            messages=[{"role": "user", "content": chooser_prompt(event, cands, town)}],
            output_format=Choice,
        )
        picked = None
        if response.stop_reason == "end_turn" and response.parsed_output is not None:
            wanted = response.parsed_output.gazetteer_id
            picked = next((c for c in cands if c.gazetteer_id == wanted), None)
        log.append({"location_text": event["location_text"], "usage": response.usage,
                    "picked": picked.gazetteer_id if picked else None})  # fmt: skip
        return picked

    return choose


def choice_key(event: dict[str, Any], cands: list[Place]) -> str:
    return event["location_text"] + "|" + ",".join(c.gazetteer_id for c in cands)


def cached_chooser(cache: dict[str, str | None], live: Chooser | None = None) -> Chooser:
    """A Chooser that answers from `cache` and asks `live` (storing the answer) on a miss.

    Without `live`, a miss raises KeyError: scoring never calls the API.
    """

    def choose(event: dict[str, Any], cands: list[Place], town: Place | None) -> Place | None:
        key = choice_key(event, cands)
        if key not in cache:
            if live is None:
                raise KeyError(f"no saved geocoder choice for {key}; run src.verify_model")
            picked = live(event, cands, town)
            cache[key] = picked.gazetteer_id if picked else None
        return next((c for c in cands if c.gazetteer_id == cache[key]), None)

    return choose
