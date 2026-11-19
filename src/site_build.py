"""Build the static demo's data from the public release (no private files needed).

    uv run python -m src.site_build      # release/ledger_public.parquet -> site/data/

Writes site/data/events.geojson (located events only) and site/data/meta.json
(counts, build time, test-split scores from eval/results.csv). Anything dated within
`site.delay_hours` of the build is left out (PLAN: 48-hour delay on any map of
conflict events): an event is kept only when the end of its latest date (report date
or event date, UTC) lies at least that many hours before the build.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from src.collect import ROOT
from src.config import load_config
from src.release import PUBLIC

SITE_DATA = ROOT / "site" / "data"
RESULTS = ROOT / "eval" / "results.csv"
PAIRS_NOTE = (
    "Rule 7b pairs a Russian or Ukrainian claim of an advance with a later geolocated "
    "confirmation of the same place. The General Staff reports carry neither: every event "
    "is a Ukrainian claim, and none is a territorial advance. Pairs need the ISW corpus, "
    "planned for version 2."
)


def cutoff_date(built: datetime, delay_hours: int) -> date:
    """Latest date whose whole day (UTC) ends at least `delay_hours` before `built`."""
    return (built - timedelta(hours=delay_hours)).date() - timedelta(days=1)


def apply_delay(frame: pl.DataFrame, built: datetime, delay_hours: int) -> pl.DataFrame:
    """Keep events whose report date and event date are both on or before the cutoff."""
    last = cutoff_date(built, delay_hours)
    return frame.filter((pl.col("report_date") <= last) & (pl.col("event_date") <= last))


def feature(row: dict[str, Any]) -> dict[str, Any]:
    """One GeoJSON point with short property names (keeps the file small)."""
    props = {
        "id": row["event_id"], "t": row["event_type"], "s": row["epistemic_status"],
        "a": row["actor"], "d": row["event_date"].isoformat(),
        "r": row["report_date"].isoformat(), "p": row["place_name"], "o": row["oblast"],
        "g": row["geo_precision"], "q": row["quantity"], "c": row["cluster_id"],
        "n": row["cluster_size"], "u": row["source_url"], "es": row["evidence_start"],
        "ee": row["evidence_end"], "k": row["confirmed_by"],
    }  # fmt: skip
    point = [round(row["lon"], 4), round(row["lat"], 4)]
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": point},
            "properties": props}  # fmt: skip


def geojson(frame: pl.DataFrame) -> dict[str, Any]:
    located = frame.filter(pl.col("lat").is_not_null() & pl.col("lon").is_not_null())
    return {"type": "FeatureCollection", "features": [feature(r) for r in located.to_dicts()]}


def split_scores(path: Path = RESULTS) -> dict[str, dict[str, float]]:
    """Event F1 with its interval per system, from the test-split rows of results.csv."""
    out: dict[str, dict[str, float]] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["split"] == "test" and r["metric"] in ("event_f1", "event_f1_low",
                                                        "event_f1_high"):  # fmt: skip
                out.setdefault(r["system"], {})[r["metric"]] = float(r["value"])
    return out


def meta(frame: pl.DataFrame, kept: pl.DataFrame, built: datetime, cfg: dict[str, Any],
         scores: dict[str, dict[str, float]]) -> dict[str, Any]:  # fmt: skip
    located = kept.filter(pl.col("lat").is_not_null())
    return {
        "built_at": built.isoformat(timespec="minutes"),
        "delay_hours": cfg["site"]["delay_hours"],
        "cutoff_date": cutoff_date(built, cfg["site"]["delay_hours"]).isoformat(),
        "first_report": str(kept["report_date"].min()) if kept.height else None,
        "last_report": str(kept["report_date"].max()) if kept.height else None,
        "n_events": kept.height,
        "n_located": located.height,
        "n_withheld_delay": frame.height - kept.height,
        "n_reports": kept["report_id"].n_unique(),
        "by_type": dict(Counter(kept["event_type"].to_list()).most_common()),
        "by_status": dict(Counter(kept["epistemic_status"].to_list()).most_common()),
        "systems": sorted(kept["system"].unique().to_list()),
        "n_pairs": int(kept["confirmed_by"].is_not_null().sum()),
        "pairs_note": PAIRS_NOTE,
        "test_scores": scores,
    }


def build(built: datetime | None = None, out: Path = SITE_DATA,
          public: Path = PUBLIC) -> dict[str, Any]:  # fmt: skip
    cfg = load_config()
    built = built or datetime.now(UTC)
    frame = pl.read_parquet(public)
    kept = apply_delay(frame, built, cfg["site"]["delay_hours"])
    info = meta(frame, kept, built, cfg, split_scores())
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.geojson").write_text(json.dumps(geojson(kept), separators=(",", ":")))
    (out / "meta.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    info = build()
    print(
        f"site data: {info['n_located']} located of {info['n_events']} events, reports "
        f"{info['first_report']} to {info['last_report']}; {info['n_withheld_delay']} "
        f"withheld by the {info['delay_hours']}-hour delay (cutoff {info['cutoff_date']})"
    )


if __name__ == "__main__":
    main()
