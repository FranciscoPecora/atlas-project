"""Hard case 13 applied to the dev key: a paragraph that opens with two front directions.

    uv run python -m src.keyfix

The reviewer model wrote such paragraphs two ways (one event per kind per
direction with no count, or one event per kind for both directions with the
count). Hard case 13 of the guideline rules for the second form. This script
rewrites the first form into the second in eval/gold/dev/ and changes nothing else.

The counts are read by a person and listed in COUNTS; code checks that each
number is in the event's evidence span before it is written (SPEC 2.2).
Dev key only: the test key is locked and is never opened here.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.collect import DATA
from src.extract import dev_gsu_dates
from src.labels import GOLD, SPEC
from src.prelabel import DIRECTION, paragraph_spans
from src.verify_det import has_quantity

METHOD_SUFFIX = "+case13"
# (report date, paragraph) -> count per event type, read from the paragraph by a person
COUNTS: dict[tuple[str, int], dict[str, int]] = {
    ("2026-07-21", 6): {"ground_assault": 1, "air_strike": 2, "shelling": 50},
    ("2026-08-06", 4): {"ground_assault": 7, "air_strike": 2, "shelling": 75},
}


def two_directions(paragraph: str) -> tuple[str, list[str]] | None:
    """(phrase, [direction words]) when the paragraph opens with two directions."""
    m = DIRECTION.match(paragraph)
    if not m:
        return None
    words = re.split(r"\s+(?:і|та)\s+", re.sub(r"\s+напрямк\w*$", "", m.group(1)))
    return (m.group(1), words) if len(words) == 2 else None


def merge(
    records: list[dict[str, Any]], text: str, span: tuple[int, int], counts: dict[str, int]
) -> list[dict[str, Any]]:
    """Records with the per-direction events of one paragraph merged, one per type.

    Raises ValueError when a type has no count or its count is not in the evidence."""
    a, b = span
    found = two_directions(text[a:b])
    if found is None:
        return records
    phrase, words = found
    out: list[dict[str, Any]] = []
    done: set[str] = set()
    for r in records:
        if not (a <= r["evidence_start"] < b and r.get("location_text") in words):
            out.append(r)
            continue
        kind = r["event_type"]
        if kind in done:
            continue
        done.add(kind)
        if kind not in counts:
            raise ValueError(f"no count listed for {kind}")
        if not has_quantity(text[r["evidence_start"] : r["evidence_end"]], counts[kind]):
            raise ValueError(f"count {counts[kind]} for {kind} is not in its evidence span")
        method = r.get("label_method") or ""
        out.append(
            {
                **r,
                "location_text": phrase,
                "quantity": counts[kind],
                "label_method": method
                if method.endswith(METHOD_SUFFIX)
                else method + METHOD_SUFFIX,
            }
        )
    return out


def main() -> None:
    for day in dev_gsu_dates(SPEC.read_text(encoding="utf-8")):
        path = GOLD / "dev" / f"gsu-{day}__FULL__pass1.jsonl"
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        records = [
            json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()
        ]
        before = len(records)
        spans = paragraph_spans(text)
        for (d, n), counts in COUNTS.items():
            if d == day:
                records = merge(records, text, spans[n - 1], counts)
        if len(records) != before:
            path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
            )
        print(f"gsu-{day}: {before} -> {len(records)} events")


if __name__ == "__main__":
    main()
