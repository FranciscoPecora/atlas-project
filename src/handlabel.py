"""Hand labelling of General Staff dev reports, from the English reading aid.

    uv run python -m src.handlabel build            # write data/handlabel/label.html
    uv run python -m src.handlabel save ANSWERS     # turn the saved answers into records

The annotator reads no Ukrainian, so Label Studio (select Ukrainian text, copy
place names) was too slow to use. This page shows one paragraph at a time in
English. The annotator picks a kind of event, clicks the places it happened at,
and presses Enter: one event per place. The page never shows the machine-made
answer key, so the labels are an independent human reading.

What the annotator decides: whether there is an event, its kind, its place, who
acted, and its count. What code fills in: the place name as written in the
Ukrainian (from the clicked occurrence), the evidence offsets (the sentence that
holds the place, or the paragraph), the date (General Staff reports describe the
previous day) and status `ua_claimed`.

The place buttons come from the translation's list of place names (a model
found the names; it did not say whether anything happened there).

The page holds source text and lives under data/handlabel/ (git-ignored). The
records hold offsets and place names only and are written to eval/human/dev/.
They are NOT the gold key: eval/score.py does not read that folder.
Dev reports only: `unit_task_data` refuses a test-split report.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.audit import english_paragraphs, glossary, render_page
from src.collect import DATA, ROOT
from src.extract import default_date, dev_gsu_dates
from src.labels import SPEC
from src.prelabel import CLAIM_SOURCE, DIRECTION, SENTENCE_END, paragraph_spans, spans
from src.review import unit_task_data
from src.schema import EventType
from src.translate import load_translation
from src.verify_det import has_quantity

PAGE = DATA / "handlabel" / "label.html"
TEMPLATE = Path(__file__).with_name("handlabel_page.html")
OUT = ROOT / "eval" / "human" / "dev"
LOG = OUT / "import_log.json"
METHOD = "human-from-translation-v1"
JOINER = re.compile(r"\s+(?:і|та)\s+")


def key_span(key: str) -> tuple[int, int]:
    """ "120-131" to (120, 131): a place button is named by its offsets in the report."""
    s, e = key.split("-")
    return int(s), int(e)


def place_chips(text: str, a: int, b: int, names: dict[str, str]) -> list[dict[str, Any]]:
    """First occurrence in text[a:b] of each listed place name, in text order.

    Whole words only, longest names first, so "Лиман" is not found inside
    "Лиманському" and "Новий Комар" wins over "Комар"."""
    taken: list[tuple[int, int]] = []
    chips = []
    for name in sorted(names, key=len, reverse=True):
        for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text[a:b]):
            s, e = a + m.start(), a + m.end()
            if not any(s < te and ts < e for ts, te in taken):
                taken.append((s, e))
                chips.append({"key": f"{s}-{e}", "uk": name, "en": names[name]})
                break
    return sorted(chips, key=lambda c: key_span(c["key"]))


def direction_chips(text: str, a: int, b: int, names: dict[str, str]) -> list[dict[str, Any]]:
    """Front directions named at the start of the paragraph ("На X і Y напрямках ...")."""
    m = DIRECTION.match(text[a:b])
    if not m:
        return []
    words = JOINER.split(re.sub(r"\s+напрямк\w*$", "", m.group(1)))
    chips, at = [], a + m.start(1)
    for w in words:
        s = text.index(w, at)
        at = s + len(w)
        chips.append({"key": f"{s}-{at}", "uk": w, "en": names.get(w)})
    return chips


def english_directions(english: str, n: int) -> list[str | None]:
    """English names of the `n` directions a paragraph starts with, or n times None.

    Read from the translation's opening words: "In the Kursk and Sumy directions ...",
    or the same with "axis" or "axes"."""
    m = re.match(r"(?:In|On) the (.+?) (?:directions?|ax[ie]s)\b", english)
    found = re.split(r",\s*|\s+and\s+", m.group(1)) if m else []
    return list(found) if len(found) == n else [None] * n


def items_for(rid: str, text: str, aid: dict[str, str]) -> list[dict[str, Any]]:
    """One page item per paragraph: English, Ukrainian, and the place buttons."""
    names, english = glossary(aid["places"]), english_paragraphs(aid["translation"])
    items = []
    for n, (a, b) in enumerate(paragraph_spans(text), start=1):
        dirs = direction_chips(text, a, b, names)
        for d, en in zip(dirs, english_directions(english.get(n, ""), len(dirs)), strict=True):
            d["en"] = d["en"] or en
        held = [key_span(d["key"]) for d in dirs]
        places = [
            c
            for c in place_chips(text, a, b, names)
            if not any(key_span(c["key"])[0] < e and s < key_span(c["key"])[1] for s, e in held)
        ]
        items.append(
            {
                "id": f"{rid}:{n}",
                "report_id": rid,
                "paragraph": n,
                "english": english.get(n, "(no translation)"),
                "ukrainian": text[a:b],
                "places": places,
                "directions": dirs,
            }
        )
    return items


def sentence_at(text: str, a: int, b: int, offset: int) -> tuple[int, int]:
    """The sentence of paragraph text[a:b] that contains `offset`."""
    for s, e in spans(text, a, b, SENTENCE_END):
        if s <= offset < e:
            return s, e
    return a, b


def to_record(
    event: dict[str, Any], text: str, para: tuple[int, int], data: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """A saved page event as a record with code-computed offsets, or (None, problem)."""
    a, b = para
    if event.get("event_type") not in set(EventType):
        return None, f"unknown event type {event.get('event_type')!r}"
    place, location = event.get("place"), None
    start, end = a, b
    if isinstance(place, str) and place.startswith("free:"):
        return None, f"place typed by hand, not in the list: {place[5:]!r}"
    if place:
        s, e = key_span(place)
        if not (a <= s < e <= b):
            return None, f"place {place} is outside its paragraph"
        location = text[s:e]
        start, end = sentence_at(text, a, b, s)
    quantity = event.get("quantity")
    if quantity is not None and not has_quantity(text[start:end], quantity):
        start, end = a, b  # the number may sit in another sentence of the paragraph
        if not has_quantity(text[a:b], quantity):
            return None, f"count {quantity} is not in the paragraph"
    return {
        "event_type": event["event_type"],
        "epistemic_status": "ua_claimed",
        "claim_source": CLAIM_SOURCE,
        "actor": event.get("actor") or "RU",
        "target": "RU" if event.get("actor") == "UA" else "UA",
        "location_text": location,
        "geo_precision": 2 if location else None,  # set by code, as in the key; not judged
        "event_date": default_date(data),
        "units": [],
        "equipment": [],
        "quantity": quantity,
        "report_id": data["report_id"],
        "source": data["source"],
        "report_date": data["report_date"],
        "sector": data["sector"],
        "evidence_start": start,
        "evidence_end": end,
        "text_sha256": data["text_sha256"],
        "source_url": data["source_url"],
        "annotation_pass": 1,
        "label_method": METHOD,
    }, None


def report_records(
    answers: dict[str, Any], text: str, data: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Records, problems and progress facts for one report."""
    rid, paras = data["report_id"], paragraph_spans(text)
    records: list[dict[str, Any]] = []
    problems: list[str] = []
    dropped: list[dict[str, Any]] = []
    done = seconds = 0
    for n, para in enumerate(paras, start=1):
        answer = answers.get(f"{rid}:{n}") or {}
        done += bool(answer.get("done"))
        seconds += float(answer.get("seconds") or 0)
        for event in answer.get("events", []):
            record, problem = to_record(event, text, para, data)
            if record is None:
                problems.append(f"{rid} paragraph {n}: {problem}")
                dropped.append({"paragraph": n, "problem": problem})
            else:
                records.append(record)
    minutes = round(seconds / 60, 1)
    for r in records:
        r["minutes"] = minutes
    facts = {"paragraphs": len(paras), "done": done, "minutes": minutes, "dropped": dropped}
    return records, problems, facts


def out_path(report_id: str, out_dir: Path = OUT) -> Path:
    return out_dir / f"{report_id}__FULL__human1.jsonl"


def build() -> None:
    spec_text = SPEC.read_text(encoding="utf-8")
    items: list[dict[str, Any]] = []
    for day in dev_gsu_dates(spec_text):
        data = unit_task_data(day, spec_text)  # refuses test-split reports
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        aid = load_translation(day)
        if aid is None:
            raise SystemExit(f"no translation for {day}; run src.translate first")
        items += items_for(data["report_id"], text, aid)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(render_page(items, TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8")
    chips = sum(len(i["places"]) + len(i["directions"]) for i in items)
    print(f"{len(items)} paragraphs, {chips} place buttons -> {PAGE.relative_to(ROOT)}")


def save(answers_path: Path) -> None:
    raw = json.loads(answers_path.read_text(encoding="utf-8"))
    if raw.get("kind") != "handlabel":
        raise SystemExit("this file was not saved by the hand-labelling page")
    spec_text = SPEC.read_text(encoding="utf-8")
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}
    for day in dev_gsu_dates(spec_text):
        data = unit_task_data(day, spec_text)
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        records, problems, facts = report_records(raw.get("answers", {}), text, data)
        print(f"{data['report_id']}: {facts['done']} of {facts['paragraphs']} paragraphs done, "
              f"{len(records)} events, {facts['minutes']} minutes")  # fmt: skip
        for p in problems:
            print(f"  PROBLEM {p}")
        if facts["done"] < facts["paragraphs"]:
            print("  not written: the report is not finished")
            continue
        path = out_path(data["report_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
        )
        print(f"  written: {path.relative_to(ROOT)}")
        log[data["report_id"]] = {**facts, "events": len(records)}
    if log:
        LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sv = sub.add_parser("save")
    sv.add_argument("answers", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        build()
    else:
        save(args.answers)


if __name__ == "__main__":
    main()
