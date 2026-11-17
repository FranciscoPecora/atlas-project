"""Gazetteer: one table of Ukrainian places, and a lookup from a name as written.

    uv run python -m src.gazetteer build          # write data/gazetteer.parquet
    uv run python -m src.gazetteer lookup Ясного  # print the best rows

Sources (downloaded to data/raw/gazetteer/, never committed):
GeoNames `UA.txt` with `admin1CodesASCII.txt`, and OpenStreetMap place nodes
(Overpass JSON, optional). OSM nodes are merged into a GeoNames row when they
share a name and lie within MERGE_KM; the rest are added as their own rows.

Coordinates in the ledger come only from this table (CLAUDE.md hard rule).
Lookup is exact, then by stem (Ukrainian reports write places in the genitive
or accusative: "Ясного" for "Ясне"), then fuzzy.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
from rapidfuzz import fuzz, process

from eval.score import haversine_km
from src.collect import DATA, ROOT

RAW = DATA / "raw" / "gazetteer"
TABLE = DATA / "gazetteer.parquet"
MERGE_KM = 5.0
FUZZY_MIN = 85
PLACE_CODES = ("P", "A")  # populated places and administrative areas (oblasts, raions)
OSM_NAME_KEYS = ("name", "name:uk", "name:ru", "name:en", "old_name", "old_name:uk", "alt_name")
# Words that mark a direction or area, not part of the place name.
FILLER = {"напрямку", "напрямок", "напрямках", "району", "районі", "області", "область"}
# Case endings, longest first. Stripping them maps "Ясного" and "Ясне" to one stem.
ENDINGS = (
    "ського", "ському", "ськими", "ських", "ськом", "ської", "ською", "ський", "ська",
    "ське", "ські", "ську", "ого", "ому", "ими", "ої", "ою", "их", "ій", "ім", "ів",
    "ях", "ах", "ям", "ам", "ий", "ей", "а", "я", "у", "ю", "і", "и", "е", "о", "ь", "й",
)  # fmt: skip
SKY = "ськ"  # adjective suffix: "Покровському" (direction) and "Покровськ" (town) share it


@dataclass(frozen=True)
class Place:
    gazetteer_id: str
    name: str
    lat: float
    lon: float
    oblast: str
    population: int
    kind: str
    aliases: tuple[str, ...] = field(default=())


def normalise(name: str) -> str:
    """Lowercase, NFC, one apostrophe and dash form, single spaces."""
    s = unicodedata.normalize("NFC", name).lower()
    s = re.sub(r"[’ʼ`‘]", "'", s)
    s = re.sub(r"[‐-―−]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def stem_word(word: str) -> str:
    for ending in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            base = word[: -len(ending)]
            return base + SKY if ending.startswith(SKY) else base
    return word


def stem(name: str) -> str:
    """Stem of every word, without direction or area filler words."""
    words = [w for w in re.split(r"[ ]", normalise(name)) if w and w not in FILLER]
    return " ".join("-".join(stem_word(part) for part in w.split("-")) for w in words)


def read_admin1(path: Path) -> dict[str, str]:
    """ "UA.13" -> "Kharkiv" from GeoNames admin1CodesASCII.txt."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        code, name, *_ = line.split("\t")
        if code.startswith("UA."):
            out[code[3:]] = name
    return out


def read_geonames(path: Path, admin1: dict[str, str]) -> list[Place]:
    places = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row[6] not in PLACE_CODES:
                continue
            aliases = {row[1], row[2], *(a for a in row[3].split(",") if a)}
            places.append(
                Place(
                    gazetteer_id=f"gn:{row[0]}",
                    name=row[1],
                    lat=float(row[4]),
                    lon=float(row[5]),
                    oblast=admin1.get(row[10], ""),
                    population=int(row[14] or 0),
                    kind=row[7],
                    aliases=tuple(sorted(aliases)),
                )
            )
    return places


def read_osm(path: Path) -> list[Place]:
    """Place nodes from an Overpass JSON answer."""
    places = []
    for el in json.loads(path.read_text(encoding="utf-8")).get("elements", []):
        tags = el.get("tags", {})
        names = [n.strip() for k in OSM_NAME_KEYS for n in tags.get(k, "").split(";") if n.strip()]
        if el.get("type") != "node" or not names:
            continue
        pop = re.sub(r"\D", "", tags.get("population", ""))
        places.append(
            Place(
                gazetteer_id=f"osm:{el['id']}",
                name=tags.get("name:en") or names[0],
                lat=float(el["lat"]),
                lon=float(el["lon"]),
                oblast="",
                population=int(pop) if pop else 0,
                kind=tags.get("place", ""),
                aliases=tuple(sorted(set(names))),
            )
        )
    return places


def merge(base: list[Place], extra: list[Place], km: float = MERGE_KM) -> list[Place]:
    """Add `extra` aliases to the nearest `base` row that shares a name within `km`;
    rows with no such partner are appended. Ids of `base` rows never change."""
    by_alias: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(base):
        for a in p.aliases:
            by_alias[normalise(a)].append(i)
    out: list[Place] = list(base)
    added: dict[int, set[str]] = defaultdict(set)
    for e in extra:
        near = {i for a in e.aliases for i in by_alias.get(normalise(a), [])}
        scored = [(haversine_km(e.lat, e.lon, base[i].lat, base[i].lon), i) for i in near]
        scored = [s for s in scored if s[0] <= km]
        if scored:
            added[min(scored)[1]].update(e.aliases)
        else:
            out.append(e)
    for i, names in added.items():
        p = out[i]
        out[i] = Place(**{**p.__dict__, "aliases": tuple(sorted(set(p.aliases) | names))})
    return out


def write_table(places: list[Place], path: Path = TABLE) -> None:
    rows = [{**p.__dict__, "aliases": list(p.aliases)} for p in places]
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path)


def read_table(path: Path = TABLE) -> list[Place]:
    return [
        Place(**{**r, "aliases": tuple(r["aliases"])}) for r in pl.read_parquet(path).to_dicts()
    ]


class Gazetteer:
    """Name lookup: exact alias, then stem, then fuzzy stem. Best candidates first."""

    def __init__(self, places: list[Place]) -> None:
        self.places = places
        self.exact: dict[str, set[int]] = defaultdict(set)
        self.stems: dict[str, set[int]] = defaultdict(set)
        for i, p in enumerate(places):
            for a in p.aliases:
                self.exact[normalise(a)].add(i)
                self.stems[stem(a)].add(i)
        self._stem_keys = list(self.stems)

    def _rank(self, ids: set[int], query: str, near: tuple[float, float] | None) -> list[Place]:
        """Nearest to `near` first when it is given (the direction's main town);
        otherwise closest spelling, then population."""

        def key(i: int) -> tuple[float, bool, float, int, str]:
            p = self.places[i]
            km = haversine_km(p.lat, p.lon, *near) if near else 0.0
            best = max(fuzz.ratio(query, normalise(a)) for a in p.aliases)
            area = not p.kind.startswith("PPL") and p.gazetteer_id.startswith("gn:")
            return (km, area, -best, -p.population, p.gazetteer_id)

        return [self.places[i] for i in sorted(ids, key=key)]

    def lookup(
        self, name: str, near: tuple[float, float] | None = None, limit: int = 5
    ) -> tuple[str, list[Place]]:
        """(how it matched, candidate places). how is exact, stem, fuzzy or none."""
        query = normalise(name)
        if query in self.exact:
            return "exact", self._rank(self.exact[query], query, near)[:limit]
        s = stem(name)
        if s in self.stems:
            return "stem", self._rank(self.stems[s], query, near)[:limit]
        hit = process.extractOne(s, self._stem_keys, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN)
        if hit:
            return "fuzzy", self._rank(self.stems[hit[0]], query, near)[:limit]
        return "none", []


ANY_DIRECTION = re.compile(r"[А-ЯІЇЄҐ][\w’'\-]*(?:\s+(?:і|та)\s+[А-ЯІЇЄҐ][\w’'\-]*)?\s+напрямк\w*")


def paragraph_direction(paragraph: str) -> str | None:
    """The front direction a paragraph names, wherever it stands in the sentence."""
    m = ANY_DIRECTION.search(paragraph)
    return m.group(0) if m else None


def dev_names(n: int, seed: int) -> list[dict[str, Any]]:
    """`n` distinct place names from the dev key, each with its paragraph's direction."""
    import random

    from src.audit import glossary, paragraph_of, read_key
    from src.prelabel import paragraph_spans
    from src.translate import load_translation

    seen: dict[str, dict[str, Any]] = {}
    for r in read_key():
        name = r.get("location_text")
        if not name or name in seen:
            continue
        day = r["report_date"]
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        spans = paragraph_spans(text)
        a, b = spans[paragraph_of(spans, r["evidence_start"]) - 1]
        english = glossary((load_translation(day) or {}).get("places", "")).get(name, "")
        seen[name] = {"name": name, "direction": paragraph_direction(text[a:b]), "english": english}
    names = sorted(seen)
    return [seen[k] for k in sorted(random.Random(seed).sample(names, min(n, len(names))))]


def direction_anchor(
    gaz: Gazetteer, direction: str | None, anchors: dict[str, list[str]]
) -> tuple[float, float] | None:
    """Coordinates of the town a front direction is named after (config.yaml)."""
    if not direction:
        return None
    words = set(stem(direction).split())
    for adjective, (town, oblast) in anchors.items():
        if stem(adjective) in words:
            rows = [p for p in gaz.lookup(town, limit=50)[1] if p.oblast in (oblast, "")]
            rows.sort(key=lambda p: (not p.kind.startswith("PPL"), -p.population))
            return (rows[0].lat, rows[0].lon) if rows else None
    return None


def resolve(
    gaz: Gazetteer, name: str, near: tuple[float, float] | None, max_km: float
) -> tuple[str, Place | None, float | None]:
    """Best place for a name: nearest to the direction's town, and within max_km of it."""
    how, found = gaz.lookup(name, near)
    if not found:
        return how, None, None
    km = haversine_km(found[0].lat, found[0].lon, *near) if near else None
    if km is not None and km > max_km:
        return "too_far", None, km
    return how, found[0], km


def check(gaz: Gazetteer, names: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve each dev name, anchored on its paragraph's direction."""
    out = []
    for item in names:
        near = direction_anchor(gaz, item["direction"], cfg["direction_anchors"])
        how, place, km = resolve(gaz, item["name"], near, cfg["max_anchor_km"])
        out.append({**item, "how": how, "place": place, "anchor_km": km})
    return out


def build(raw: Path = RAW) -> list[Place]:
    places = read_geonames(raw / "UA.txt", read_admin1(raw / "admin1CodesASCII.txt"))
    osm = raw / "osm_places.json"
    usable = osm.exists() and osm.read_bytes()[:1] == b"{"  # not an error page
    return merge(places, read_osm(osm)) if usable else places


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("lookup").add_argument("name")
    sub.add_parser("check")
    args: Any = ap.parse_args(argv)
    if args.cmd == "build":
        places = build()
        write_table(places)
        n_osm = sum(p.gazetteer_id.startswith("osm:") for p in places)
        print(f"{len(places)} places ({n_osm} from OSM only) -> {TABLE.relative_to(ROOT)}")
    elif args.cmd == "lookup":
        how, found = Gazetteer(read_table()).lookup(args.name)
        print(how)
        for p in found:
            print(f"  {p.gazetteer_id} {p.name} ({p.oblast}) {p.lat:.4f},{p.lon:.4f}")
    else:
        from src.config import load_config

        cfg = load_config()
        results = check(Gazetteer(read_table()), dev_names(30, cfg["eval"]["seed"]), cfg["geocode"])
        for r in results:
            p = r["place"]
            got = f"{p.name} ({p.oblast})" if p else "NOT RESOLVED"
            km = "" if r["anchor_km"] is None else f" {r['anchor_km']:.0f} km from direction town"
            print(f"{r['name']} [{r['english']}] -> {r['how']}: {got}{km}")
        print(f"resolved {sum(r['place'] is not None for r in results)} of {len(results)}")


if __name__ == "__main__":
    main()
