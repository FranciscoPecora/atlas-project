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


MODEL_SYSTEMS = ("B2", "S1", "S1-medium")  # read from data/pred/ when present


def model_predictions(
    reports: list[tuple[str, str, str]], texts: dict[str, str]
) -> tuple[dict[str, list[Event]], dict[str, dict[str, Any]]]:
    """Ungeocoded records of the model systems, and run facts (cost, time, rejections).

    S2 is not a separate run: it is S1's output after deterministic verification.
    """
    from statistics import median

    from src.extract import read_pred, to_records
    from src.verify_det import REASONS, verify

    preds: dict[str, list[Event]] = {}
    facts: dict[str, dict[str, Any]] = {}
    for system in MODEL_SYSTEMS:
        runs = {rid: read_pred(system, rid) for rid, _, _ in reports}
        if any(r is None for r in runs.values()):
            continue  # not run on every report of this split
        meta = {rid: {"report_id": rid, "source": src, "report_date": day, "sector": "FULL"}
                for rid, src, day in reports}  # fmt: skip
        preds[system] = [
            rec for rid, run in runs.items()
            for rec in to_records(run["events"], texts[rid], meta[rid], system)
        ]  # fmt: skip
        first = next(iter(runs.values()))
        facts[system] = {
            "cost_usd_per_report": sum(r["cost_usd"] for r in runs.values()) / len(runs),
            "seconds_median": median(r["seconds"] for r in runs.values()),
            "model": f"model={first['model']} effort={first['effort']}",
        }
        if system == "S1":
            kept: list[Event] = []
            rejected: dict[str, int] = dict.fromkeys(REASONS, 0)
            for rid in runs:
                mine = [r for r in preds["S1"] if r["report_id"] == rid]
                ok, why = verify(mine, texts[rid])
                kept += [{**r, "id": r["id"].replace(":S1:", ":S2:"), "system": "S2"} for r in ok]
                for reason, n in why.items():
                    rejected[reason] += n
            preds["S2"] = kept
            facts["S2"] = {**facts["S1"], "rejected": rejected, "n_before": len(preds["S1"])}
    if "S1" in preds:
        s3_predictions(reports, texts, runs_s1={rid: read_pred("S1", rid) for rid, _, _ in reports},
                       preds=preds, facts=facts)  # fmt: skip
    return preds, facts


def s3_predictions(
    reports: list[tuple[str, str, str]],
    texts: dict[str, str],
    runs_s1: dict[str, Any],
    preds: dict[str, list[Event]],
    facts: dict[str, dict[str, Any]],
) -> None:
    """Add S3-H and S3-S (ungeocoded) and their facts, for variants verified on every report.

    Cost and time per report are extraction plus verification plus geocoder model calls.
    """
    from collections import Counter
    from statistics import median

    from src.s3 import SYSTEMS, verified

    for system in SYSTEMS:
        try:
            done = {rid: verified(system, rid, texts[rid]) for rid, _, _ in reports}
        except FileNotFoundError:
            continue  # not run on every report of this split
        meta = {rid: {"report_id": rid, "source": src, "report_date": day, "sector": "FULL"}
                for rid, src, day in reports}  # fmt: skip
        preds[system] = [
            {**r, **meta[rid], "id": f"{rid}:{system}:{i}", "system": system}
            for rid, (kept, _) in done.items() for i, r in enumerate(kept)
        ]  # fmt: skip
        removed: Counter[str] = Counter()
        dropped: Counter[str] = Counter()
        for _, run in done.values():
            removed.update(run["counts"]["removed"])
            dropped.update(run["counts"]["dropped"])
        cost = [
            runs_s1[rid]["cost_usd"] + run["cost_usd"] + run.get("geocode_cost_usd", 0.0)
            for rid, (_, run) in done.items()
        ]  # fmt: skip
        first = next(iter(done.values()))[1]
        facts[system] = {
            "cost_usd_per_report": sum(cost) / len(cost),
            "seconds_median": median(
                runs_s1[rid]["seconds"] + run["seconds"] for rid, (_, run) in done.items()
            ),  # fmt: skip
            "model": f"model={runs_s1[reports[0][0]]['model']} verifier={first['model']} "
            f"effort={first['effort']}",
            "removed": dict(removed),
            "dropped": dict(dropped),
            "n_before": sum(run["n_records"] for _, run in done.values()),
        }


def metric_rows(
    preds: dict[str, list[Event]], gold: list[Event], ev: dict[str, Any], split: str
) -> list[dict[str, Any]]:
    """Print each system's scores on `gold` and return them as result rows (no stamp)."""
    rows = []
    k, d = ev["match_km"], ev["match_days"]
    units = {(g["report_id"], g["sector"]) for g in gold}
    report_ids = sorted({g["report_id"] for g in gold})
    print(f"-- {split}: {len(gold)} gold events in {len(report_ids)} reports")
    for system, events in preds.items():
        res = score(events, gold, k, d, ev["bootstrap_resamples"], ev["seed"])
        kept = in_gold_units(events, units)
        matches = []
        for rid in report_ids:
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
            value = "" if v is None else round(v, 4)
            rows.append({"split": split, "system": system, "metric": m, "value": value, "n": n})
    return rows


def fact_rows(facts: dict[str, dict[str, Any]], eur_per_usd: float, split: str) -> list[dict]:
    """Measured cost, speed and rejection counts of the model systems, as result rows."""
    rows = []
    for system, f in facts.items():
        usd = f["cost_usd_per_report"]
        print(f"{system}: ${usd:.5f} = {usd * eur_per_usd:.5f} EUR per report, "
              f"median {f['seconds_median']:.1f} s per report")  # fmt: skip
        values = [
            ("cost_usd_per_report", round(usd, 6), ""),
            ("cost_eur_per_report", round(usd * eur_per_usd, 6), ""),
            ("seconds_per_report_median", round(f["seconds_median"], 1), ""),
        ]
        for reason, n in f.get("rejected", {}).items():
            values.append((f"rejected_{reason}", n, f["n_before"]))
        for kind in ("removed", "dropped"):
            for field, n in sorted(f.get(kind, {}).items()):
                values.append((f"verifier_{kind}_{field}", n, f["n_before"]))
        if "rejected" in f:
            print(f"  rejected of {f['n_before']}: {f['rejected']}")
        if "removed" in f:
            print(
                f"  verifier, of {f['n_before']}: fields removed {f['removed']}, "
                f"records dropped for {f['dropped']}"
            )
        rows += [
            {"split": split, "system": system, "metric": m, "value": v, "n": n}
            for m, v, n in values
        ]
    return rows


def main(argv: list[str] | None = None) -> None:
    from src.baselines import b0_regex, b1_gliner
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
    preds: dict[str, list[Event]] = {b0_regex.SYSTEM: [], b1_gliner.SYSTEM: []}
    gliner = b1_gliner.load_model(cfg["models"], "gsu")
    threshold = cfg["models"]["b1_threshold"]
    for rid, src, day in reports:
        gold += geocode([g for g in gold_raw if g["report_id"] == rid], texts[rid], gaz, geo)
        if src == "gsu":
            preds["B0"] += geocode(b0_regex.extract(texts[rid], rid, day), texts[rid], gaz, geo)
            b1 = b1_gliner.extract(gliner, texts[rid], rid, day, threshold)
            preds["B1"] += geocode(b1, texts[rid], gaz, geo)
    facts: dict[str, dict[str, Any]] = {}
    if args.split == "dev":  # model systems are run on test only in milestone 5
        from src.geocode import cached_chooser
        from src.s3 import SYSTEMS, geocode_s3, load_choices

        raw, facts = model_predictions(reports, texts)
        chooser = cached_chooser(load_choices())  # saved choices only: no API call here
        day_of = {rid: day for rid, _, day in reports}
        for system, events in raw.items():
            preds[system] = []
            for rid in texts:
                mine = [x for x in events if x["report_id"] == rid]
                if system in SYSTEMS:
                    preds[system] += geocode_s3(mine, texts[rid], day_of[rid], gaz, geo, chooser)
                else:
                    preds[system] += geocode(mine, texts[rid], gaz, geo)
    order = ["B0", "B1", "B2", "S1", "S2", "S3-H", "S3-S", "S1-medium"]
    preds = {s: preds[s] for s in order if s in preds}
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
    print(f"{args.split}: {located} of {named} named gold places geocoded")
    rows = metric_rows(preds, gold, ev, args.split)
    example = f"gsu-{cfg['extract']['example_report']}"
    if args.split == "dev" and facts:
        # The prompt's worked examples come from one dev report; score without it too.
        held = [g for g in gold if g["report_id"] != example]
        rows += metric_rows(preds, held, ev, "dev-heldout")
    rows += fact_rows(facts, cfg["cost"]["eur_per_usd"], args.split)
    for row in rows:
        extra = facts.get(row["system"], {}).get("model")
        row.update(stamp, config=f"{used} {extra}" if extra else used)
    append_results(rows)
    print(f"{len(rows)} rows appended to {RESULTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
