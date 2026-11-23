"""Exploratory, not pre-registered: Russian capture claims beside General Staff assaults.

    uv run python -m src.cross_source

For each located RUMOD `territorial_advance`, counts General Staff `ground_assault`
events within `radius_km` in the `window` days before the claim and in the `window`
days after it. Reads only the public release. The numbers are descriptive: places of a
shared name can sit at the wrong village (FAILURES pattern 1), and a General Staff
assault "in the area of" a village is not a statement about who holds it.
"""

from __future__ import annotations

import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from src.collect import ROOT

LEDGER = ROOT / "release" / "ledger_public.parquet"


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular distance in km; within 0.1% of haversine at these distances."""
    rad = math.pi / 180
    x = (lon2 - lon1) * rad * math.cos((lat1 + lat2) / 2 * rad)
    return 6371 * math.hypot(x, (lat2 - lat1) * rad)


def claims_and_assaults(ledger: pl.DataFrame) -> tuple[list[tuple], list[tuple]]:
    """(date, lat, lon) of located RUMOD advance claims and of located GSU assaults."""

    def rows(source: str, etype: str) -> list[tuple]:
        f = ledger.filter(
            (pl.col("source") == source) & (pl.col("event_type") == etype)
            & pl.col("lat").is_not_null()
        )  # fmt: skip
        day = pl.col("event_date")
        day = day.str.to_date() if f.schema["event_date"] == pl.String else day.cast(pl.Date)
        return f.select(day, "lat", "lon").rows()

    return rows("rumod", "territorial_advance"), rows("gsu", "ground_assault")


def compare(
    claims: list[tuple[date, float, float]],
    assaults: list[tuple[date, float, float]],
    radius_km: float = 5.0,
    window: int = 30,
) -> dict[str, Any]:
    """Claims with a nearby assault before (0 to window days) and after (1 to window)."""
    before = after = 0
    lags: list[int] = []
    for day, lat, lon in claims:
        near = [d for d, a, b in assaults if km(lat, lon, a, b) <= radius_km]
        pre = [(day - d).days for d in near if 0 <= (day - d).days <= window]
        post = [(d - day).days for d in near if 1 <= (d - day).days <= window]
        if pre:
            before += 1
            lags.append(min(pre))
        after += bool(post)
    return {
        "claims": len(claims),
        "assault_before": before,
        "assault_after": after,
        "median_days_since_assault": statistics.median(lags) if lags else None,
    }


def main(path: Path = LEDGER) -> None:
    claims, assaults = claims_and_assaults(pl.read_parquet(path))
    out = compare(claims, assaults)
    print(f"{out['claims']} located Russian capture claims (5 km, 30 days):")
    print(f"  General Staff assault nearby before the claim: {out['assault_before']}")
    print(f"  General Staff assault nearby after the claim:  {out['assault_after']}")
    print(f"  median days from the last assault to the claim: {out['median_days_since_assault']}")


if __name__ == "__main__":
    main()
