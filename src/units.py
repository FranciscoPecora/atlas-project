"""Resolve unit names to unit ids with an alias table grown by hand (pipeline step 6).

    uv run python -m src.units propose [--system S1]   # write data/units_review.csv
    uv run python -m src.units apply                    # add approved rows to the table

data/unit_aliases.csv (committed) has one row per alias: unit_id, alias, added.
Matching is exact after normalisation, then fuzzy (rapidfuzz token_set_ratio at
or above `units.fuzzy_min`), and two names match only if they carry the same
numbers: "3rd Assault Brigade" never matches "47th Assault Brigade" however
similar the words are. No model is used at run time.

`propose` collects every unit name the system extracted, and writes names the
table does not resolve to data/units_review.csv with a suggested unit (the best
fuzzy alias, or a new id). The owner sets `approve` to y on the rows to keep,
optionally edits `unit_id`, and runs `apply`. Nothing enters the table unapproved.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from src.collect import DATA, ROOT
from src.config import load_config

TABLE = DATA / "unit_aliases.csv"
REVIEW = DATA / "units_review.csv"
TABLE_FIELDS = ["unit_id", "alias", "added"]
REVIEW_FIELDS = ["name", "count", "unit_id", "nearest_alias", "score", "approve"]
ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th|-?(?:а|я|й|ї|ої|ого|ий|ій))\b", re.IGNORECASE)


def normalise(name: str) -> str:
    """NFC, casefold, ordinals to bare numbers ("3rd" -> "3", "3-я" -> "3"), no punctuation."""
    text = unicodedata.normalize("NFC", name).casefold()
    text = ORDINAL.sub(r"\1", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def numbers(name: str) -> tuple[str, ...]:
    return tuple(sorted(re.findall(r"\d+", normalise(name))))


def read_table(path: Path = TABLE) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def best_alias(name: str, table: list[dict[str, str]]) -> tuple[dict[str, str] | None, float]:
    """The alias row closest to `name` among rows with the same numbers, and its score."""
    query, nums = normalise(name), numbers(name)
    best, score = None, 0.0
    for row in table:
        if numbers(row["alias"]) != nums:
            continue
        s = (
            100.0
            if normalise(row["alias"]) == query
            else fuzz.token_set_ratio(query, normalise(row["alias"]))
        )
        if s > score:
            best, score = row, s
    return best, score


def resolve(name: str, table: list[dict[str, str]], fuzzy_min: float) -> str | None:
    """The unit id for a name as written, or None when no alias is close enough."""
    row, score = best_alias(name, table)
    return row["unit_id"] if row is not None and score >= fuzzy_min else None


def unit_ids(
    units: list[dict[str, Any]], table: list[dict[str, str]], fuzzy_min: float
) -> list[str]:
    """Resolved ids for an event's unit mentions, in order, without repeats or misses."""
    found = (resolve(u["name"], table, fuzzy_min) for u in units)
    return list(dict.fromkeys(i for i in found if i))


def new_id(name: str, taken: set[str]) -> str:
    """A readable id from the name ("u:3-assault-brigade"), made unique."""
    base = "u:" + "-".join(normalise(name).split())[:48]
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


def proposals(
    names: dict[str, int], table: list[dict[str, str]], fuzzy_min: float
) -> list[dict[str, Any]]:
    """Review rows for names the table does not resolve, most frequent first."""
    rows = []
    taken = {r["unit_id"] for r in table}
    for name, count in sorted(names.items(), key=lambda kv: (-kv[1], kv[0])):
        if resolve(name, table, fuzzy_min):
            continue
        row, score = best_alias(name, table)
        if row is not None and score >= fuzzy_min * 0.8:
            unit = row["unit_id"]  # a near miss: suggest merging into that unit
        else:
            unit = new_id(name, taken)
            taken.add(unit)
        rows.append({"name": name, "count": count, "unit_id": unit,
                     "nearest_alias": row["alias"] if row else "", "score": round(score),
                     "approve": ""})  # fmt: skip
    return rows


def approved(review: list[dict[str, str]], today: str) -> list[dict[str, str]]:
    """Table rows for review lines marked y (any case); everything else is ignored."""
    return [
        {"unit_id": r["unit_id"].strip(), "alias": r["name"], "added": today}
        for r in review
        if r.get("approve", "").strip().lower() == "y" and r["unit_id"].strip()
    ]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def extracted_names(system: str, pred_dir: Path = DATA / "pred") -> dict[str, int]:
    """How often each unit name occurs in a system's saved extractions."""
    counts: dict[str, int] = {}
    for path in sorted((pred_dir / system).glob("*.json")):
        for e in json.loads(path.read_text(encoding="utf-8")).get("events", []):
            for u in e.get("units") or []:
                counts[u["name"]] = counts.get(u["name"], 0) + 1
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["propose", "apply"])
    ap.add_argument("--system", default="S1")
    args = ap.parse_args(argv)
    fuzzy_min = load_config()["units"]["fuzzy_min"]
    table = read_table()
    if args.step == "propose":
        names = extracted_names(args.system)
        rows = proposals(names, table, fuzzy_min)
        write_csv(REVIEW, rows, REVIEW_FIELDS)
        print(f"{len(names)} distinct unit names in {args.system}; {len(rows)} not resolved "
              f"-> {REVIEW.relative_to(ROOT)}")  # fmt: skip
        return
    with REVIEW.open(encoding="utf-8", newline="") as f:
        new = approved(list(csv.DictReader(f)), date.today().isoformat())
    known = {(r["unit_id"], r["alias"]) for r in table}
    added = [r for r in new if (r["unit_id"], r["alias"]) not in known]
    write_csv(TABLE, table + added, TABLE_FIELDS)
    print(f"{len(added)} aliases added; table has {len(table) + len(added)}")


if __name__ == "__main__":
    main()
