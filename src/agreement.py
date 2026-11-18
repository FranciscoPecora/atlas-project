"""Human pass against the machine-made dev key, General Staff reports.

    uv run python -m src.agreement            # print the comparison
    uv run python -m src.agreement --record   # also append rows to eval/results.csv

Compares eval/human/dev/ (src.handlabel) with eval/gold/dev/. Dev reports only.

Events are compared in units, paragraph by paragraph:

- an event at a village is the unit (paragraph, place name as written);
- an event at the paragraph's front direction is the unit (paragraph, direction),
  one per event type. A paragraph can open with two directions, and the key
  writes such events in two ways (one per direction, or one for both), so
  events of one type at any of the paragraph's directions count as one unit;
- an event with no place is the unit (paragraph, no place).

Inside a unit, events of the same type are paired first, then the rest in order.
A pair with two different types is a type disagreement, not two unmatched events.
This is stricter on place than SPEC 5.1 (same name, not 10 km) and needs no
geocoding: both sides copy the name from the same text.

Human events that could not be imported (place typed by hand) are counted as
human-only, from eval/human/dev/import_log.json.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from eval.score import append_results, prf
from src.collect import DATA, ROOT
from src.config import config_hash, load_config
from src.extract import dev_gsu_dates
from src.handlabel import LOG, out_path
from src.labels import GOLD, SPEC
from src.prelabel import DIRECTION, paragraph_spans
from src.stability import kappa

OUT = ROOT / "eval" / "human" / "dev" / "comparison.json"
Unit = tuple[int, str, str]


def paragraph_of(spans: list[tuple[int, int]], offset: int) -> int:
    """1-based number of the paragraph that holds `offset` (0 when none does)."""
    return next((n for n, (a, b) in enumerate(spans, start=1) if a <= offset < b), 0)


def direction_phrase(paragraph: str) -> str:
    """The front directions a paragraph opens with ("X і Y напрямках"), or ""."""
    m = DIRECTION.match(paragraph)
    return m.group(1) if m else ""


def unit(record: dict[str, Any], text: str, spans: list[tuple[int, int]]) -> Unit:
    """(paragraph, kind, name): kind is "place", "direction" or "none"."""
    n = paragraph_of(spans, record["evidence_start"])
    place = record.get("location_text")
    if not place:
        return n, "none", ""
    a, b = spans[n - 1] if n else (0, 0)
    phrase = direction_phrase(text[a:b])
    words = [w for w in place.split() if not w.startswith("напрямк")]
    if phrase and all(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", phrase) for w in words):
        return n, "direction", ""
    return n, "place", place


def collapse(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One event per type; of several, the first that states a count."""
    by_type: dict[str, dict[str, Any]] = {}
    for e in events:
        kept = by_type.get(e["event_type"])
        if kept is None or (kept.get("quantity") is None and e.get("quantity") is not None):
            by_type[e["event_type"]] = e
    return list(by_type.values())


def units(records: list[dict[str, Any]], text: str) -> dict[Unit, list[dict[str, Any]]]:
    spans = paragraph_spans(text)
    out: dict[Unit, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        out[unit(r, text, spans)].append(r)
    return {u: collapse(es) if u[1] == "direction" else es for u, es in out.items()}


def pair_unit(
    human: list[dict[str, Any]], key: list[dict[str, Any]]
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Pairs, human-only and key-only events of one unit: same type first, then in order."""
    h, k, pairs = list(human), list(key), []
    for e in list(h):
        same = next((g for g in k if g["event_type"] == e["event_type"]), None)
        if same is not None:
            pairs.append((e, same))
            h.remove(e)
            k.remove(same)
    n = min(len(h), len(k))
    return pairs + list(zip(h[:n], k[:n], strict=True)), h[n:], k[n:]


def compare(human: list[dict[str, Any]], key: list[dict[str, Any]], text: str) -> dict[str, Any]:
    """Pairs and leftovers for one report."""
    hu, ku = units(human, text), units(key, text)
    pairs: list[tuple[dict, dict, Unit]] = []
    only_h: list[tuple[dict, Unit]] = []
    only_k: list[tuple[dict, Unit]] = []
    for u in sorted(set(hu) | set(ku)):
        p, h, k = pair_unit(hu.get(u, []), ku.get(u, []))
        pairs += [(a, b, u) for a, b in p]
        only_h += [(e, u) for e in h]
        only_k += [(e, u) for e in k]
    return {"pairs": pairs, "human_only": only_h, "key_only": only_k}


def summary(pairs: list[tuple[dict, dict]], human_only: int, key_only: int) -> dict[str, Any]:
    """Counts and agreement rates over all reports."""
    n = len(pairs)
    counted = [
        (h, k) for h, k in pairs if h.get("quantity") is not None or k.get("quantity") is not None
    ]
    same = lambda f, ps: sum(h.get(f) == k.get(f) for h, k in ps)  # noqa: E731
    return {
        "human_events": n + human_only,
        "key_events": n + key_only,
        "paired": n,
        "human_only": human_only,
        "key_only": key_only,
        **{f"event_{m}": round(v, 4) for m, v in prf(n, n + human_only, n + key_only).items()},
        "type_same": same("event_type", pairs),
        "kappa_event_type": kappa(pairs, "event_type"),
        "actor_same": same("actor", pairs),
        "pairs_with_a_count": len(counted),
        "count_same": same("quantity", counted),
    }


def describe(e: dict[str, Any], u: Unit) -> dict[str, Any]:
    """A disagreement line: no source text, only the paragraph, labels and place name."""
    place = "(front direction)" if u[1] == "direction" else e.get("location_text")
    return {"report_id": e["report_id"], "paragraph": u[0], "event_type": e["event_type"],
            "actor": e.get("actor"), "place": place, "quantity": e.get("quantity")}  # fmt: skip


def disagreements(res: dict[str, Any]) -> list[dict[str, Any]]:
    out = [{"kind": "human only", **describe(e, u)} for e, u in res["human_only"]]
    out += [{"kind": "key only", **describe(e, u)} for e, u in res["key_only"]]
    for h, k, u in res["pairs"]:
        for field in ("event_type", "actor", "quantity"):
            if h.get(field) != k.get(field):
                out.append({"kind": f"different {field}", **describe(h, u),
                            "human": h.get(field), "key": k.get(field)})  # fmt: skip
    return sorted(out, key=lambda d: (d["report_id"], d["paragraph"], d["kind"]))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help="append rows to eval/results.csv")
    args = ap.parse_args(argv)
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}
    pairs: list[tuple[dict, dict]] = []
    lines: list[dict[str, Any]] = []
    human_only = key_only = dropped = 0
    days = []
    for day in dev_gsu_dates(SPEC.read_text(encoding="utf-8")):
        rid = f"gsu-{day}"
        if not out_path(rid).exists():
            print(f"{rid}: no human pass yet")
            continue
        days.append(day)
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        key = read_jsonl(GOLD / "dev" / f"{rid}__FULL__pass1.jsonl")
        res = compare(read_jsonl(out_path(rid)), key, text)
        lost = log.get(rid, {}).get("dropped", [])
        lines += disagreements(res) + [
            {"kind": "human only", "report_id": rid, "paragraph": d["paragraph"],
             "event_type": None, "actor": None, "place": "(typed by hand)", "quantity": None}
            for d in lost
        ]  # fmt: skip
        pairs += [(h, k) for h, k, _ in res["pairs"]]
        human_only += len(res["human_only"]) + len(lost)
        key_only += len(res["key_only"])
        dropped += len(lost)
        print(f"{rid}: {len(res['pairs'])} paired, {len(res['human_only']) + len(lost)} "
              f"human only, {len(res['key_only'])} key only")  # fmt: skip
    total = {**summary(pairs, human_only, key_only), "human_not_imported": dropped}
    print(json.dumps(total, indent=1))
    for d in lines:
        print("  " + json.dumps(d, ensure_ascii=False))
    OUT.write_text(
        json.dumps({"reports": days, "summary": total, "disagreements": lines},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # fmt: skip
    if args.record:
        cfg = load_config()
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
        base = {
            "commit": commit,
            "config_hash": config_hash(cfg),
            "date": date.today().isoformat(),
            "split": "dev",
            "system": "human-vs-key",
            "config": "reports=" + "+".join(days),
        }
        metrics = [
            ("event_precision", total["human_events"]),
            ("event_recall", total["key_events"]),
            ("event_f1", total["paired"]),
            ("kappa_event_type", total["paired"]),
        ]
        append_results(
            [{**base, "metric": m, "value": round(total[m], 4), "n": n} for m, n in metrics]
        )


if __name__ == "__main__":
    main()
