"""Event matching and scores, exactly as SPEC.md section 5.1 and 5.4 state them.

Events are plain dicts with: id, report_id, sector, event_type, event_date
(ISO string), lat, lon (both None when there is no location). Gold and
predicted events use the same keys.

This module is the only code allowed to open eval/gold/test/, and only when
run through `make eval-test`. The loaders and the command line arrive with
the baselines; this file holds the scoring logic and is tested on hand-made
cases in tests/test_score.py.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date
from typing import Any

Event = dict[str, Any]
EARTH_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def has_location(e: Event) -> bool:
    return e.get("lat") is not None and e.get("lon") is not None


def day_gap(p: Event, g: Event) -> int:
    return abs((date.fromisoformat(p["event_date"]) - date.fromisoformat(g["event_date"])).days)


def dist_km(p: Event, g: Event) -> float | None:
    """Distance for the location rule: 0 when both have no location, None when only one has."""
    if has_location(p) and has_location(g):
        return haversine_km(p["lat"], p["lon"], g["lat"], g["lon"])
    return 0.0 if not has_location(p) and not has_location(g) else None


def valid(p: Event, g: Event, k_km: float, d_days: int) -> bool:
    """SPEC 5.1 rules 1 to 4."""
    if (p["report_id"], p["sector"]) != (g["report_id"], g["sector"]):
        return False
    if p["event_type"] != g["event_type"] or day_gap(p, g) > d_days:
        return False
    d = dist_km(p, g)
    return d is not None and d <= k_km


def match(
    preds: list[Event], gold: list[Event], k_km: float = 10, d_days: int = 1
) -> list[tuple[Event, Event]]:
    """One-to-one greedy matching, closest pair first (SPEC 5.1 pseudocode)."""
    pairs = [
        (dist_km(p, g), day_gap(p, g), p["id"], g["id"], p, g)
        for p in preds
        for g in gold
        if valid(p, g, k_km, d_days)
    ]
    pairs.sort(key=lambda x: x[:4])
    used_p: set[str] = set()
    used_g: set[str] = set()
    matches = []
    for _, _, pid, gid, p, g in pairs:
        if pid not in used_p and gid not in used_g:
            matches.append((p, g))
            used_p.add(pid)
            used_g.add(gid)
    return matches


def prf(tp: int, n_pred: int, n_gold: int) -> dict[str, float]:
    """Precision, recall and F1; each is 0 when undefined."""
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gold if n_gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def in_gold_units(preds: list[Event], gold_units: set[tuple[str, str]]) -> list[Event]:
    """Predictions in sections that are not gold units are discarded before matching."""
    return [p for p in preds if (p["report_id"], p["sector"]) in gold_units]


def counts_by_report(
    preds: list[Event], gold: list[Event], k_km: float = 10, d_days: int = 1
) -> dict[str, tuple[int, int, int]]:
    """Per report: (TP, number predicted, number gold). Matching never crosses reports."""
    by_p: dict[str, list[Event]] = defaultdict(list)
    by_g: dict[str, list[Event]] = defaultdict(list)
    for p in preds:
        by_p[p["report_id"]].append(p)
    for g in gold:
        by_g[g["report_id"]].append(g)
    return {
        rid: (len(match(by_p[rid], by_g[rid], k_km, d_days)), len(by_p[rid]), len(by_g[rid]))
        for rid in sorted(set(by_p) | set(by_g))
    }


def total(counts: list[tuple[int, int, int]]) -> dict[str, float]:
    tp, n_pred, n_gold = (sum(c[i] for c in counts) for i in range(3))
    return {"tp": tp, "fp": n_pred - tp, "fn": n_gold - tp, **prf(tp, n_pred, n_gold)}


def bootstrap_f1(
    per_report: dict[str, tuple[int, int, int]], resamples: int = 2000, seed: int = 20261116
) -> tuple[float, float]:
    """95% percentile interval for F1. The resampling unit is the report (SPEC 5.4)."""
    reports = sorted(per_report)
    if not reports:
        return 0.0, 0.0
    rng = random.Random(seed)
    values = sorted(
        total([per_report[rng.choice(reports)] for _ in reports])["f1"] for _ in range(resamples)
    )
    return values[int(0.025 * resamples)], values[min(resamples - 1, int(0.975 * resamples))]


def score(
    preds: list[Event],
    gold: list[Event],
    k_km: float = 10,
    d_days: int = 1,
    resamples: int = 2000,
    seed: int = 20261116,
) -> dict[str, Any]:
    """Event precision, recall, F1 and the F1 interval for one system on one split."""
    units = {(g["report_id"], g["sector"]) for g in gold}
    per_report = counts_by_report(in_gold_units(preds, units), gold, k_km, d_days)
    low, high = bootstrap_f1(per_report, resamples, seed)
    return {**total(list(per_report.values())), "f1_low": low, "f1_high": high}


def grid(
    preds: list[Event], gold: list[Event], kms: list[float], days: list[int]
) -> dict[tuple[float, int], float]:
    """F1 for every (K km, D days) cell of the sensitivity grid (SPEC 5.3)."""
    units = {(g["report_id"], g["sector"]) for g in gold}
    kept = in_gold_units(preds, units)
    return {
        (k, d): total(list(counts_by_report(kept, gold, k, d).values()))["f1"]
        for k in kms
        for d in days
    }
