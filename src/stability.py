"""Reviewer stability (SPEC.md amendment A1): is the reviewer model consistent with itself?

    uv run python -m src.stability

The reviewer is run a second time on the GSU reports in rows 1 to 6 of the
rotation table (dev units). Events of the two runs are matched as in SPEC 5.1,
and Cohen's kappa on event_type and epistemic_status is reported over the
matched pairs, target >= 0.75. The second run is not written to the key.
"""

from __future__ import annotations

import subprocess
from datetime import date
from typing import Any

import anthropic
from dotenv import load_dotenv
from sklearn.metrics import cohen_kappa_score

from eval.score import append_results, match
from src.collect import DATA, ROOT
from src.config import config_hash, load_config
from src.gazetteer import Gazetteer, read_table
from src.geocode import geocode
from src.labels import SPEC, gold_units
from src.review import GUIDELINE, gold_path, review_report, to_records, unit_task_data

TARGET = 0.75


def kappa(pairs: list[tuple[dict, dict]], field: str) -> float | None:
    """Cohen's kappa of a field over matched pairs. 1.0 when both runs use one single
    value everywhere (kappa is undefined there, and agreement is complete)."""
    a = [str(p.get(field)) for p, _ in pairs]
    b = [str(g.get(field)) for _, g in pairs]
    if not pairs:
        return None
    if len(set(a) | set(b)) == 1:
        return 1.0
    return float(cohen_kappa_score(a, b))


def loose_match(first: list[dict], second: list[dict]) -> list[tuple[dict, dict]]:
    """Match two runs on place and date only, so that a changed type shows up as a
    disagreement instead of as an unmatched event."""
    same = [{**e, "event_type": "any"} for e in first]
    other = [{**e, "event_type": "any"} for e in second]
    by_id = {e["id"]: e for e in first + second}
    return [(by_id[p["id"]], by_id[g["id"]]) for p, g in match(same, other, k_km=10, d_days=1)]


def compare(first: list[dict], second: list[dict]) -> dict[str, Any]:
    pairs = loose_match(first, second)
    return {
        "first": len(first),
        "second": len(second),
        "matched": len(pairs),
        "kappa_event_type": kappa(pairs, "event_type"),
        "kappa_epistemic_status": kappa(pairs, "epistemic_status"),
    }


def with_ids(records: list[dict], tag: str) -> list[dict]:
    return [{**r, "id": f"{r['report_id']}:{tag}:{i}"} for i, r in enumerate(records)]


def main() -> None:
    import json

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    spec = SPEC.read_text(encoding="utf-8")
    guideline = GUIDELINE.read_text(encoding="utf-8")
    client = anthropic.Anthropic()
    gaz = Gazetteer(read_table())
    days = [u.report_date.isoformat() for u in gold_units(spec) if u.source == "gsu" and u.row <= 6]
    first: list[dict] = []
    second: list[dict] = []
    for day in days:
        data = unit_task_data(day, spec)
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        lines = gold_path(day).read_text(encoding="utf-8").splitlines()
        key = [json.loads(x) for x in lines if x.strip()]
        again, _ = to_records(review_report(client, cfg["models"], text, guideline), text, data)
        first += geocode(with_ids(key, "run1"), text, gaz, cfg["geocode"])
        second += geocode(with_ids(again, "run2"), text, gaz, cfg["geocode"])
    res = compare(first, second)
    print(f"reports {days}: {res}")
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    base = {
        "commit": commit,
        "config_hash": config_hash(cfg),
        "date": date.today().isoformat(),
        "split": "dev",
        "system": "gold-reviewer-stability",
        "config": f"gold_review={cfg['models']['gold_review']} reports={'+'.join(days)}",
    }
    rows = [
        {**base, "metric": m, "value": round(res[m], 4), "n": res["matched"]}
        for m in ("kappa_event_type", "kappa_epistemic_status")
        if res[m] is not None
    ]
    append_results(rows)
    for m in ("kappa_event_type", "kappa_epistemic_status"):
        ok = res[m] is not None and res[m] >= TARGET
        print(f"{m}: {res[m]} -> {'OK' if ok else 'BELOW TARGET'} (target {TARGET})")


if __name__ == "__main__":
    main()
