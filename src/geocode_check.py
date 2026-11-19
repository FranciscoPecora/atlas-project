"""Hand check of the geocoder on dev places (owner's choice, 19 Nov: not the SPEC metric).

    uv run python -m src.geocode_check build    # write data/audit/geocode_check.csv
    uv run python -m src.geocode_check page     # the marking page (make mark-places)
    uv run python -m src.geocode_check score [ANSWERS]   # from the page's saved file

SPEC 5.3 "Geocoding accuracy@10 km" counts matched pairs whose gold event has
geo_precision 1. Every located dev gold event is precision 2, so that metric has
n = 0 on dev, and gold coordinates come from this same geocoder, so it would be
circular anyway. This check is separate and labelled as such.

Sample: `geocode_check.places` distinct (place as written, front direction) pairs
from the dev key, seeded. Each row lists the gazetteer rows the name could be
(namesakes within `max_anchor_km` of the direction's town, or the 10 largest when
the paragraph names no direction), in id order so the list does not hint at the
geocoder's choice, with a map link each. The geocoder's choice is not shown. The
owner writes the letter of the right row in `pick`, `none` if no row is right, or
`?` if unsure. The CSV holds English text of the reports, so it stays local
(git-ignored); `pick` and the ids are copied to eval/audit/ to commit.

The marking page (`make mark-places`) needs no knowledge of the front: it also
shows, as grey dots, the other villages named in the same paragraph whose names
exist once in the gazetteer, and the owner picks the pin among them. So the check
measures agreement with the paragraph's other villages, a strong proxy for the
right namesake but not ground truth.

Score: each geocoder variant is run on the dev gold events at the checked places;
an event is right when its point is within 10 km of the picked row. Accuracy and
median error are reported over events and over places.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import string
from pathlib import Path
from statistics import median
from typing import Any

from eval.score import haversine_km
from src.collect import DATA, ROOT
from src.gazetteer import Gazetteer, Place, direction_place, paragraph_direction

LOCAL = DATA / "audit" / "geocode_check.csv"
ANSWERS_JSON = ROOT / "eval" / "audit" / "geocode_check_answers.json"  # ids and picks only
PAGE = DATA / "audit" / "places_check.html"
TEMPLATE = Path(__file__).with_name("geocode_page.html")
DOWNLOADS = Path.home() / "Downloads" / "claimline-places-answers.json"
MAX_ROWS = 12
LETTERS = string.ascii_uppercase


def english_paragraph(translation: str, n: int) -> str:
    """Paragraph `n` (1-based) of a stored translation ("[n] starts: ...\\nEnglish")."""
    for block in re.split(r"\n\n(?=\[\d+\] )", translation.strip()):
        head, _, body = block.partition("\n")
        if head.startswith(f"[{n}] "):
            return body.strip()
    return ""


def candidates(gaz: Gazetteer, name: str, town: Place | None, max_km: float) -> list[Place]:
    """Rows the name could be: namesakes near the town, else the largest; in id order."""
    _, rows = gaz.lookup(name, limit=100_000)
    if town is not None:
        rows = [r for r in rows if haversine_km(r.lat, r.lon, town.lat, town.lon) <= max_km]
    else:
        rows = sorted(rows, key=lambda r: -r.population)[:10]
    return sorted(rows[:MAX_ROWS], key=lambda r: r.gazetteer_id)


def osm_link(p: Place) -> str:
    return f"https://www.openstreetmap.org/?mlat={p.lat:.5f}&mlon={p.lon:.5f}#map=12/{p.lat:.5f}/{p.lon:.5f}"


def describe(p: Place, town: Place | None) -> str:
    km = (
        f", {haversine_km(p.lat, p.lon, town.lat, town.lon):.0f} km from {town.name}"
        if town
        else ""
    )
    return f"{p.name} ({p.oblast or 'oblast unknown'}, pop. {p.population}{km}) {osm_link(p)}"


def sample_places(items: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    """`n` distinct (name, direction) items, seeded, in name order."""
    distinct = {(i["name"], i["direction"] or ""): i for i in items}
    keys = sorted(distinct)
    picked = random.Random(seed).sample(keys, min(n, len(keys)))
    return [distinct[k] for k in sorted(picked)]


def row(item: dict[str, Any], cands: list[Place], town: Place | None) -> dict[str, str]:
    out = {
        "place_id": f"{item['name']}|{item['direction'] or ''}",
        "place_uk": item["name"],
        "place_en": item.get("english", ""),
        "direction_town": town.name if town else "",
        "paragraph_en": item.get("paragraph_en", ""),
        "n_rows": str(len(cands)),
    }
    for letter, p in zip(LETTERS, cands, strict=False):
        out[f"row_{letter}"] = describe(p, town)
    out["ids"] = " ".join(p.gazetteer_id for p in cands)
    return {**out, "pick": ""}


def page_item(item: dict[str, Any], cands: list[Place], town: Place | None) -> dict[str, Any]:
    """One screen of the marking page: the sentence, the town and every candidate with its point."""
    return {
        "id": f"{item['name']}|{item['direction'] or ''}",
        "place_uk": item["name"],
        "place_en": item.get("english", ""),
        "paragraph_en": item.get("paragraph_en", ""),
        "town": {"name": town.name, "lat": town.lat, "lon": town.lon} if town else None,
        "cands": [
            {"id": p.gazetteer_id, "name": p.name, "oblast": p.oblast, "population": p.population,
             "lat": p.lat, "lon": p.lon,
             "km": round(haversine_km(p.lat, p.lon, town.lat, town.lon)) if town else None}
            for p in cands
        ],
    }  # fmt: skip


def read_answers(path: Path) -> dict[str, str | None]:
    """The page's saved file as {place_id: gazetteer_id, or None for 'none'}; unsure left out."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("kind") != "places":
        raise ValueError(f"{path} is not a place-check answers file")
    return {k: (None if v == "none" else v) for k, v in raw["answers"].items() if v != "unsure"}


def read_picks(path: Path) -> dict[str, str | None]:
    """{place_id: picked gazetteer_id or None for 'none'}; unsure and blank rows are skipped."""
    picks: dict[str, str | None] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            pick = r["pick"].strip().upper()
            if pick in ("", "?"):
                continue
            ids = r["ids"].split()
            if pick == "NONE":
                picks[r["place_id"]] = None
            elif len(pick) == 1 and LETTERS.index(pick) < len(ids):
                picks[r["place_id"]] = ids[LETTERS.index(pick)]
            else:
                raise ValueError(f"{r['place_id']}: pick {pick!r} is not a listed letter")
    return picks


def errors_km(events: list[dict[str, Any]], truth: dict[str, Place]) -> list[float]:
    """Error in km per geocoded event whose place has a hand-picked row (inf if no point)."""
    out = []
    for e in events:
        right = truth.get(e["place_id"])
        if right is None:
            continue
        if e.get("lat") is None:
            out.append(float("inf"))
        else:
            out.append(haversine_km(e["lat"], e["lon"], right.lat, right.lon))
    return out


def summary(errors: list[float], km: float = 10.0) -> tuple[float | None, float | None, int]:
    """(share within km, median error, n)."""
    if not errors:
        return None, None, 0
    return sum(x <= km for x in errors) / len(errors), median(errors), len(errors)


def gold_items() -> list[dict[str, Any]]:
    """Every located dev gold event as a check item: name, direction, English context."""

    from src.audit import glossary, paragraph_of, read_key
    from src.prelabel import paragraph_spans

    items = []
    for r in read_key():
        if not r.get("location_text"):
            continue
        day = r["report_date"]
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        spans = paragraph_spans(text)
        n = paragraph_of(spans, r["evidence_start"])
        a, b = spans[n - 1]
        en_path = DATA / "text" / "gsu_en" / f"{day}.json"
        en = json.loads(en_path.read_text(encoding="utf-8")) if en_path.exists() else {}
        items.append({
            "name": r["location_text"], "direction": paragraph_direction(text[a:b]),
            "english": glossary(en.get("places", "")).get(r["location_text"], ""),
            "paragraph_en": english_paragraph(en.get("translation", ""), n), "record": r,
            "paragraph": (day, n),
        })  # fmt: skip
    return items


def neighbours(
    item: dict[str, Any], items: list[dict[str, Any]], gaz: Gazetteer
) -> list[dict[str, Any]]:
    """Other villages named in the item's paragraph (the one shown) that match one gazetteer row.

    They are the reference the owner judges against: the right namesake sits among them.
    Unique names need no disambiguation, so they do not depend on the rules being checked.
    """
    out: dict[str, dict[str, Any]] = {}
    for other in items:
        name = other["name"]
        if other["paragraph"] != item["paragraph"] or name == item["name"] or "напрям" in name:
            continue
        _, rows = gaz.lookup(name, limit=2)
        if len(rows) == 1 and name not in out:
            p = rows[0]
            out[name] = {"name": other.get("english") or p.name, "lat": p.lat, "lon": p.lon}
    return list(out.values())


def pid(item: dict[str, Any]) -> str:
    return f"{item['name']}|{item['direction'] or ''}"


def locate(
    items: list[dict[str, Any]], gaz: Gazetteer, geo: dict[str, Any], with_previous: bool
) -> list[dict[str, Any]]:
    """Each item's gold record geocoded by the rules alone, or with the previous-day rule."""
    from src.geocode import geocode
    from src.s3 import previous_events

    out = []
    for day in sorted({i["record"]["report_date"] for i in items}):
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        mine = [i for i in items if i["record"]["report_date"] == day]
        prev = previous_events(day, gaz, geo) if with_previous else None
        done = geocode([i["record"] for i in mine], text, gaz, geo, previous=prev)
        out += [{**e, "place_id": pid(i)} for i, e in zip(mine, done, strict=True)]
    return out


def disagreements(items: list[dict[str, Any]], gaz: Gazetteer, geo: dict[str, Any]) -> set[str]:
    """Places where the previous-day rule picks a different row than the rules alone."""
    a, b = locate(items, gaz, geo, False), locate(items, gaz, geo, True)
    return {
        x["place_id"] for x, y in zip(a, b, strict=True) if x["gazetteer_id"] != y["gazetteer_id"]
    }


def main(argv: list[str] | None = None) -> None:
    from src.config import load_config
    from src.gazetteer import read_table

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["build", "page", "score"])
    ap.add_argument("answers", nargs="?", type=Path, default=DOWNLOADS,
                    help="the file the page saved (score step)")  # fmt: skip
    args = ap.parse_args(argv)
    cfg = load_config()
    geo = cfg["geocode"]
    gaz = Gazetteer(read_table())
    items = gold_items()
    sample = sample_places(items, cfg["geocode_check"]["places"], cfg["geocode_check"]["seed"])
    in_sample = {pid(i) for i in sample}
    differ = disagreements(items, gaz, geo)
    extra = [i for i in {pid(i): i for i in items}.values() if pid(i) in differ - in_sample]
    if args.step == "page":
        shown = []
        for item in sample + sorted(extra, key=pid):
            town = direction_place(gaz, item["direction"], geo["direction_anchors"])
            cands = candidates(gaz, item["name"], town, geo["max_anchor_km"])
            shown.append({**page_item(item, cands, town), "extra": pid(item) not in in_sample,
                          "neighbours": neighbours(item, items, gaz)})  # fmt: skip
        items = shown
        blob = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
        PAGE.parent.mkdir(parents=True, exist_ok=True)
        PAGE.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*ITEMS*/[]", blob), "utf-8")
        with_ref = sum(bool(i["neighbours"]) for i in items)
        print(f"{len(items)} places -> {PAGE.relative_to(ROOT)}; {with_ref} have other "
              "villages from the same sentence to compare with")  # fmt: skip
        return
    if args.step == "build":
        rows = []
        for item in sample:
            town = direction_place(gaz, item["direction"], geo["direction_anchors"])
            rows.append(row(item, candidates(gaz, item["name"], town, geo["max_anchor_km"]), town))
        fields = list(dict.fromkeys(k for r in rows for k in r))
        fields.remove("pick")
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        with LOCAL.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[*fields, "pick"], restval="")
            writer.writeheader()
            writer.writerows(rows)
        print(f"{len(rows)} places ({len(items)} located dev gold events) -> "
              f"{LOCAL.relative_to(ROOT)}")  # fmt: skip
        return
    picks = read_answers(args.answers)
    ANSWERS_JSON.write_text(args.answers.read_text(encoding="utf-8"), encoding="utf-8")
    by_id = {p.gazetteer_id: p for p in gaz.places}
    truth = {pid: by_id[g] for pid, g in picks.items() if g is not None}
    print(f"{len(picks)} places judged; {len(picks) - len(truth)} have no right row in the "
          "gazetteer (counted as misses for every variant)")  # fmt: skip
    missing = {k for k, g in picks.items() if g is None}
    groups = {"random sample": in_sample, "places where the two rules disagree": differ}
    # SPEC 5.3's metric is undefined on dev (no precision-1 gold event); recorded as such.
    rows: list[dict[str, Any]] = [
        {"split": "dev", "system": "S3-H", "metric": "geocoding_accuracy_10km", "value": "", "n": 0}
    ]
    for label, ids in groups.items():
        checked = [i for i in items if pid(i) in ids and pid(i) in picks]
        print(f"-- {label}: {len({pid(i) for i in checked})} places judged")
        for variant, prev in (("rules", False), ("rules+previous_day", True)):
            located = locate(checked, gaz, geo, prev)
            errs = errors_km(located, truth) + [float("inf")] * sum(
                e["place_id"] in missing for e in located
            )
            acc, med, n = summary(errs)
            if n:
                print(f"{variant}: accuracy@10km {acc:.3f} over {n} gold events, median error "
                      f"{med:.1f} km")  # fmt: skip
                system = "geocoder-rules" if not prev else "geocoder-rules+previous_day"
                split = "dev-place-check" if label == "random sample" else "dev-place-disagree"
                rows.append(
                    {
                        "split": split,
                        "system": system,
                        "metric": "hand_accuracy_10km",
                        "value": round(acc, 4),
                        "n": n,
                    }
                )
                rows.append({"split": split, "system": system, "metric": "hand_median_error_km",
                             "value": round(med, 1), "n": n})  # fmt: skip

    import subprocess
    from datetime import date

    from eval.score import append_results
    from src.config import config_hash

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()  # fmt: skip
    note = (
        "owner's picks among namesakes, judged by the paragraph's uniquely named villages "
        "(a proxy, not ground truth); SPEC 5.3 metric undefined on dev: n=0 precision-1"
    )
    for r in rows:
        r.update(commit=commit, config_hash=config_hash(cfg), date=date.today().isoformat(),
                 config=note)  # fmt: skip
    append_results(rows)
    print(f"{len(rows)} rows appended to eval/results.csv")


if __name__ == "__main__":
    main()
