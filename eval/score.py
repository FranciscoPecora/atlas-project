"""Event matching and scores, exactly as SPEC.md section 5.1 and 5.4 state them.

Events are plain dicts with: id, report_id, sector, event_type, event_date
(ISO string), lat, lon (both None when there is no location). Gold and
predicted events use the same keys.

This module is the only code allowed to open eval/gold/test/, and only when
run through `make eval-test`.

    uv run python -m eval.score --split dev     # what `make eval` runs
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path
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


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results.csv"
FIELDS = ["commit", "config_hash", "date", "split", "system", "metric", "value", "n", "config"]


def accuracy(matches: list[tuple[Event, Event]], field: str, only_gold_set: bool = False) -> Any:
    """Share of matched pairs with an equal field; (share, pairs counted)."""
    pairs = [(p, g) for p, g in matches if not only_gold_set or g.get(field) is not None]
    if not pairs:
        return None, 0
    return sum(p.get(field) == g.get(field) for p, g in pairs) / len(pairs), len(pairs)


def load_gold(split: str, gold_dir: Path | None = None) -> list[Event]:
    """Gold events of a split. The test split opens only under `make eval-test`."""
    if split == "test" and os.environ.get("CLAIMLINE_EVAL_TEST") != "1":
        raise PermissionError("the test split is scored only through `make eval-test`")
    folder = (gold_dir or ROOT / "eval" / "gold") / split
    events: list[Event] = []
    for path in sorted(folder.glob("*__pass1.jsonl")):
        for i, line in enumerate(filter(str.strip, path.read_text(encoding="utf-8").splitlines())):
            events.append({**json.loads(line), "id": f"{path.stem}:gold:{i}"})
    return events


def append_results(rows: list[dict[str, Any]], path: Path = RESULTS) -> None:
    """Append rows to eval/results.csv, writing the header if the file is new."""
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    from src.baselines import b0_regex
    from src.collect import DATA
    from src.config import config_hash, load_config
    from src.gazetteer import Gazetteer, read_table
    from src.geocode import geocode

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    args = ap.parse_args(argv)
    cfg = load_config()
    ev, geo = cfg["eval"], cfg["geocode"]
    gaz = Gazetteer(read_table())
    gold_raw = load_gold(args.split)
    reports = sorted({(g["report_id"], g["source"], g["report_date"]) for g in gold_raw})
    texts = {
        rid: (DATA / "text" / src / f"{day}.txt").read_text(encoding="utf-8")
        for rid, src, day in reports
    }
    gold: list[Event] = []
    preds: dict[str, list[Event]] = {b0_regex.SYSTEM: []}
    for rid, src, day in reports:
        gold += geocode([g for g in gold_raw if g["report_id"] == rid], texts[rid], gaz, geo)
        if src == "gsu":
            preds["B0"] += geocode(b0_regex.extract(texts[rid], rid, day), texts[rid], gaz, geo)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    stamp = {"commit": commit, "config_hash": config_hash(cfg), "date": date.today().isoformat()}
    used = (
        f"K={ev['match_km']}km D={ev['match_days']}d "
        f"resamples={ev['bootstrap_resamples']} seed={ev['seed']}"
    )
    located = sum(has_location(g) for g in gold)
    named = sum(bool(g.get("location_text")) for g in gold)
    print(f"{args.split}: {len(gold)} gold events in {len(reports)} reports; "
          f"{located} of {named} named places geocoded")  # fmt: skip
    rows = []
    k, d = ev["match_km"], ev["match_days"]
    units = {(g["report_id"], g["sector"]) for g in gold}
    for system, events in preds.items():
        res = score(events, gold, k, d, ev["bootstrap_resamples"], ev["seed"])
        kept = in_gold_units(events, units)
        matches = []
        for rid in texts:
            mine = [p for p in kept if p["report_id"] == rid]
            matches += match(mine, [g for g in gold if g["report_id"] == rid], k, d)
        status, n_status = accuracy(matches, "epistemic_status")
        qty, n_qty = accuracy(matches, "quantity", only_gold_set=True)
        print(
            f"{system}: P {res['precision']:.3f} R {res['recall']:.3f} F1 {res['f1']:.3f} "
            f"[{res['f1_low']:.3f}, {res['f1_high']:.3f}] "
            f"TP {res['tp']} FP {res['fp']} FN {res['fn']} | status acc {status} "
            f"(n={n_status}) | quantity exact {qty} (n={n_qty})"
        )
        cells = grid(events, gold, ev["grid_km"], ev["grid_days"])
        print("  F1 grid (km, days): " + ", ".join(f"{c}:{v:.3f}" for c, v in cells.items()))
        base = {**stamp, "split": args.split, "system": system, "config": used}
        metrics = [
            ("event_f1", res["f1"], len(gold)),
            ("event_f1_low", res["f1_low"], len(gold)),
            ("event_f1_high", res["f1_high"], len(gold)),
            ("event_precision", res["precision"], len(kept)),
            ("event_recall", res["recall"], len(gold)),
            ("status_accuracy", status, n_status),
            ("quantity_exact", qty, n_qty),
        ]
        for m, v, n in metrics:
            rows.append({**base, "metric": m, "value": "" if v is None else round(v, 4), "n": n})
    append_results(rows)
    print(f"{len(rows)} rows appended to {RESULTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
