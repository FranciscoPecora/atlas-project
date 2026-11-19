"""Assemble S3-H and S3-S records from saved runs (SPEC.md section 6).

S3 = S2 (S1 after deterministic checks) + model field verifier + geocoder with
the previous day's events and the model tie-break. Nothing here calls the API:
verdicts and geocoder choices are read from data/pred/ (written by
src/verify_model.py), so scoring is repeatable.

The previous day's events are S2 records of the report dated one day earlier,
geocoded by the rules alone (no previous day, no model), so a day's geocoding
never depends on a chain of earlier days or on the verifier variant.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.collect import DATA
from src.extract import PRED, read_pred
from src.gazetteer import Gazetteer
from src.geocode import Chooser, geocode
from src.verify_model import apply_all, s2_records

CHOICES = PRED / "geocode_choices.json"
SYSTEMS = ("S3-H", "S3-S")


def previous_events(day: str, gaz: Gazetteer, geo: dict[str, Any]) -> list[dict[str, Any]]:
    """Rules-only geocoded S2 events of the GSU report one day before `day` ([] if none)."""
    before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    path = DATA / "text" / "gsu" / f"{before}.txt"
    if not path.exists() or read_pred("S1", f"gsu-{before}") is None:
        return []
    text = path.read_text(encoding="utf-8")
    return geocode(s2_records(f"gsu-{before}", text), text, gaz, geo)


def verified(system: str, report_id: str, text: str) -> tuple[list[dict[str, Any]], dict]:
    """S2 records after the saved verdicts of `system`, and that run's saved facts."""
    run = read_pred(system, report_id)
    if run is None:
        raise FileNotFoundError(f"no {system} verdicts for {report_id}")
    records = s2_records(report_id, text)
    if len(records) != run["n_records"]:
        raise ValueError(f"{report_id}: S2 has {len(records)} records, verdicts cover "
                         f"{run['n_records']}; S1 output changed since verification")  # fmt: skip
    kept, counts = apply_all(records, run["verdicts"])
    return kept, {**run, "counts": counts}


def load_choices(path: Path = CHOICES) -> dict[str, str | None]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_choices(cache: dict[str, str | None], path: Path = CHOICES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")


def geocode_s3(
    records: list[dict[str, Any]], text: str, day: str, gaz: Gazetteer, geo: dict[str, Any],
    chooser: Chooser,
) -> list[dict[str, Any]]:  # fmt: skip
    return geocode(records, text, gaz, geo, previous_events(day, gaz, geo), chooser)
