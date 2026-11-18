"""List what a model system missed and what it invented on dev (PLAN milestone 3, step 5).

    uv run python -m eval.errors --system S1 --n 10

Writes data/pred/<system>_errors.md. That file quotes report text, so it stays
local (data/pred/ is git-ignored). Dev split only.
"""

from __future__ import annotations

import argparse
import random
from typing import Any

from eval.score import Event, load_gold, match


def unmatched(preds: list[Event], gold: list[Event], k: float, d: int) -> tuple[list, list]:
    """(gold events with no partner, predictions with no partner), matched per report."""
    missed: list[Event] = []
    invented: list[Event] = []
    for rid in sorted({e["report_id"] for e in preds + gold}):
        p = [e for e in preds if e["report_id"] == rid]
        g = [e for e in gold if e["report_id"] == rid]
        pairs = match(p, g, k, d)
        used_p = {a["id"] for a, _ in pairs}
        used_g = {b["id"] for _, b in pairs}
        missed += [e for e in g if e["id"] not in used_g]
        invented += [e for e in p if e["id"] not in used_p]
    return missed, invented


def line(e: Event, text: str) -> str:
    """One markdown bullet: type, place, date, coordinates found or not, and the quote."""
    a, b = e.get("evidence_start"), e.get("evidence_end")
    quote = text[a:b] if a is not None else e.get("evidence_quote") or "(quote not in the text)"
    where = "geocoded" if e.get("lat") is not None else "no coordinates"
    return (
        f"- `{e['report_id']}` **{e['event_type']}** at {e.get('location_text') or 'no place'} "
        f"({where}), {e['event_date']}, quantity {e.get('quantity')}\n  > {quote}"
    )


def sample(events: list[Event], n: int, seed: int) -> list[Event]:
    """At most `n` events, drawn with a fixed seed so the list can be reproduced."""
    return events if len(events) <= n else random.Random(seed).sample(events, n)


def render(
    system: str, missed: list, invented: list, texts: dict[str, str], n: int, seed: int
) -> str:
    parts = [f"# {system} on dev: {len(missed)} missed, {len(invented)} invented"]
    for title, events in (("Missed (in the key, not predicted)", missed),
                          ("Invented (predicted, not in the key)", invented)):  # fmt: skip
        parts.append(f"\n## {title}: showing {min(n, len(events))} of {len(events)}\n")
        parts += [line(e, texts[e["report_id"]]) for e in sample(events, n, seed)]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> None:
    from eval.score import model_predictions
    from src.collect import DATA
    from src.config import load_config
    from src.gazetteer import Gazetteer, read_table
    from src.geocode import geocode

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--system", default="S1")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args(argv)
    cfg = load_config()
    ev, geo = cfg["eval"], cfg["geocode"]
    gaz = Gazetteer(read_table())
    gold_raw = load_gold("dev")
    reports = sorted({(g["report_id"], g["source"], g["report_date"]) for g in gold_raw})
    texts = {
        rid: (DATA / "text" / src / f"{day}.txt").read_text(encoding="utf-8")
        for rid, src, day in reports
    }
    raw: dict[str, list[Any]] = model_predictions(reports, texts)[0]
    gold: list[Event] = []
    preds: list[Event] = []
    for rid in texts:
        gold += geocode([g for g in gold_raw if g["report_id"] == rid], texts[rid], gaz, geo)
        mine = [p for p in raw[args.system] if p["report_id"] == rid]
        preds += geocode(mine, texts[rid], gaz, geo)
    missed, invented = unmatched(preds, gold, ev["match_km"], ev["match_days"])
    out = DATA / "pred" / f"{args.system}_errors.md"
    out.write_text(
        render(args.system, missed, invented, texts, args.n, ev["seed"]), encoding="utf-8"
    )
    print(f"{args.system}: {len(missed)} missed, {len(invented)} invented -> {out}")


if __name__ == "__main__":
    main()
