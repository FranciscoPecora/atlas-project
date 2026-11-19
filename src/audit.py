"""Spot check of the machine-made GSU answer key (dev split).

    uv run python -m src.audit build            # write data/audit/audit.html
    uv run python -m src.audit build --source af   # A2 sources: data/audit/af_audit.html
    uv run python -m src.audit score ANSWERS [--split test]   # read the saved answers

Step 3 of amendment A1. `build` draws a seeded random sample of events
and paragraphs from the reviewed dev key and writes one local web page. The
annotator clicks Right/Wrong per event and Complete/Missing per paragraph, in
English. `score` reports the error rates with 95% Wilson intervals.

The page holds source text, so it lives under data/audit/ (git-ignored). The
sample and the answers hold ids, offsets and verdicts only, and are committed.
Reads eval/gold/dev/ only, never eval/gold/test/: the test page is built by
src/review.py from the records it has just made, in the same run.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.collect import DATA, ROOT
from src.config import load_config
from src.prelabel import paragraph_spans
from src.translate import load_translation

DEV = ROOT / "eval" / "gold" / "dev"
AUDIT_DIR = ROOT / "eval" / "audit"
PAGE = DATA / "audit" / "audit.html"  # dev; the test page is audit_test.html
TEMPLATE = Path(__file__).with_name("audit_page.html")
HEAD = re.compile(r"^\[(\d+)\] starts: .*$", re.M)
EVENT_VERDICTS = ("right", "wrong", "unsure")
PARAGRAPH_VERDICTS = ("complete", "missing", "unsure")


def english_paragraphs(translation: str) -> dict[int, str]:
    """Split the reading aid ("[n] starts: ...", then the English) by paragraph number."""
    marks = list(HEAD.finditer(translation))
    return {
        int(m.group(1)): translation[
            m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(translation)
        ].strip()
        for i, m in enumerate(marks)
    }


def glossary(places: str) -> dict[str, str]:
    """ "Ясного = Yasne" lines to a lookup."""
    pairs = (line.split(" = ", 1) for line in places.splitlines() if " = " in line)
    return {src: en for src, en in pairs}


def paragraph_of(spans: list[tuple[int, int]], start: int) -> int:
    """1-based number of the paragraph that contains offset `start`."""
    return next(i for i, (a, b) in enumerate(spans, start=1) if a <= start < b)


def read_key(dev_dir: Path = DEV, source: str = "gsu") -> list[dict[str, Any]]:
    """All machine-made GSU dev records, in a stable order."""
    records: list[dict[str, Any]] = []
    for path in sorted(dev_dir.glob(f"{source}-*__FULL__pass1.jsonl")):
        lines = path.read_text(encoding="utf-8").splitlines()
        records += [r for r in map(json.loads, filter(str.strip, lines)) if r.get("label_method")]
    return records


def draw(
    records: list[dict[str, Any]],
    paragraphs: dict[str, int],
    n_events: int,
    n_paragraphs: int,
    seed: int,
    skip: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Seeded sample: events from the key, paragraphs from all paragraphs of its reports.

    `skip` is an earlier sample from `draw`; its events and paragraphs are not drawn again."""
    rng = random.Random(seed)
    seen_events = {s["record"] for s in skip or [] if s["kind"] == "event"}
    seen_units = {(s["report_id"], s["paragraph"]) for s in skip or [] if s["kind"] != "event"}
    pool = [i for i in range(len(records)) if i not in seen_events]
    events = rng.sample(pool, min(n_events, len(pool)))
    units = [(rid, p) for rid in sorted(paragraphs) for p in range(1, paragraphs[rid] + 1)]
    units = [u for u in units if u not in seen_units]
    chosen = rng.sample(units, min(n_paragraphs, len(units)))
    sample = [
        {"id": f"e{n:02d}", "kind": "event", "report_id": records[i]["report_id"], "record": i}
        for n, i in enumerate(sorted(events), start=1)
    ]
    sample += [
        {"id": f"p{n:02d}", "kind": "paragraph", "report_id": rid, "paragraph": p}
        for n, (rid, p) in enumerate(sorted(chosen), start=1)
    ]
    return sample


def card(
    record: dict[str, Any], text: str, names: dict[str, str], same_kind: int = 1
) -> dict[str, Any]:
    """What the page shows for one event. Holds source text: page only, never committed."""
    place = record.get("location_text")
    return {
        "event_type": record["event_type"],
        "status": record["epistemic_status"],
        "actor": record.get("actor"),
        "target": record.get("target"),
        "place": place,
        "place_en": names.get(place or ""),
        "quantity": record.get("quantity"),
        "same_kind": same_kind,  # events of this type in the paragraph (a shared count)
        "event_date": record["event_date"],
        "quote": text[record["evidence_start"] : record["evidence_end"]],
    }


def build_items(
    sample: list[dict[str, Any]],
    records: list[dict[str, Any]],
    texts: dict[str, str],
    aids: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    items = []
    for s in sample:
        rid = s["report_id"]
        text, aid = texts[rid], aids[rid]
        spans, names = paragraph_spans(text), glossary(aid["places"])
        if s["kind"] == "event":
            chosen = [records[s["record"]]]
            number = paragraph_of(spans, chosen[0]["evidence_start"])
        else:
            number = s["paragraph"]
            a, b = spans[number - 1]
            chosen = [r for r in records if r["report_id"] == rid and a <= r["evidence_start"] < b]
        a, b = spans[number - 1]
        inside = [r for r in records if r["report_id"] == rid and a <= r["evidence_start"] < b]
        kinds = Counter(r["event_type"] for r in inside)
        items.append(
            {
                "id": s["id"],
                "kind": s["kind"],
                "report_id": rid,
                "paragraph": number,
                "english": english_paragraphs(aid["translation"]).get(number, "(no translation)"),
                "ukrainian": text[a:b],
                "events": [card(r, text, names, kinds[r["event_type"]]) for r in chosen],
            }
        )
    return items


def render_page(items: list[dict[str, Any]], template: str) -> str:
    blob = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("/*ITEMS*/[]", blob)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k of n; (0, 1) when n is 0."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - half) / (1 + z * z / n)), min(1.0, (centre + half) / (1 + z * z / n))


def score(sample: list[dict[str, Any]], answers: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Error rate of sampled events and miss rate of sampled paragraphs."""
    out: dict[str, Any] = {}
    for kind, bad, good in (("event", "wrong", "right"), ("paragraph", "missing", "complete")):
        ids = [s["id"] for s in sample if s["kind"] == kind]
        verdicts = [answers.get(i, {}).get("verdict") for i in ids]
        n_bad, n_good = verdicts.count(bad), verdicts.count(good)
        judged = n_bad + n_good
        lo, hi = wilson(n_bad, judged)
        out[kind] = {
            "sampled": len(ids),
            "judged": judged,
            bad: n_bad,
            "unsure": verdicts.count("unsure"),
            "unanswered": verdicts.count(None),
            "rate": round(n_bad / judged, 3) if judged else None,
            "interval95": [round(lo, 3), round(hi, 3)],
        }
    return out


def clean_answers(raw: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Keep verdicts and notes only; reject verdicts the page cannot produce."""
    allowed = set(EVENT_VERDICTS + PARAGRAPH_VERDICTS)
    out = {}
    for item_id, a in raw.get("answers", {}).items():
        if a.get("verdict") not in allowed:
            raise ValueError(f"{item_id}: unknown verdict {a.get('verdict')!r}")
        out[item_id] = {"verdict": a["verdict"], "note": str(a.get("note", ""))[:500]}
    return out


def committable(s: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """A sample row without text: an event is named by its offsets and type."""
    if s["kind"] != "event":
        return s
    r = records[s["record"]]
    keep = {k: v for k, v in s.items() if k != "record"}
    return {**keep, **{k: r[k] for k in ("evidence_start", "evidence_end", "event_type")}}


def pooled(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Several rounds of `score` added up. Valid only when the rounds share no item."""
    out: dict[str, Any] = {}
    for kind, bad in (("event", "wrong"), ("paragraph", "missing")):
        judged = sum(r[kind]["judged"] for r in results)
        n_bad = sum(r[kind][bad] for r in results)
        lo, hi = wilson(n_bad, judged)
        out[kind] = {
            "judged": judged,
            bad: n_bad,
            "rate": round(n_bad / judged, 3) if judged else None,
            "interval95": [round(lo, 3), round(hi, 3)],
        }
    return out


def round_sizes(cfg: dict[str, Any], audit_round: int) -> dict[str, Any]:
    """Sample sizes of one dev round: A1's sizes unless config `audit.extra_rounds` names it."""
    a = cfg["audit"]
    base = {"events": a["events"], "paragraphs": a["paragraphs"], "skip_rounds": []}
    return {**base, **a.get("extra_rounds", {}).get(audit_round, {})}


def earlier_draws(
    records: list[dict[str, Any]], counts: dict[str, int], cfg: dict[str, Any], rounds: list[int]
) -> list[dict[str, Any]]:
    """Re-draw earlier dev rounds from their seeds, to know which items they held.

    Refuses to continue if a re-drawn round differs from its committed sample file:
    that would mean the key changed, and "not drawn before" could not be guaranteed."""
    out: list[dict[str, Any]] = []
    for n in rounds:
        size = round_sizes(cfg, n)
        seed = cfg["eval"]["seed"] + n - 1
        sample = draw(records, counts, size["events"], size["paragraphs"], seed)
        on_file = json.loads(sample_path(n).read_text(encoding="utf-8"))
        if [committable(s, records) for s in sample] != on_file:
            raise SystemExit(f"round {n} cannot be reproduced from the current key")
        out += sample
    return out


def tag(source: str) -> str:
    """File-name prefix: none for GSU (A1's files keep their names), '<source>_' for A2."""
    return "" if source == "gsu" else f"{source}_"


def sample_path(audit_round: int, split: str = "dev", source: str = "gsu") -> Path:
    return AUDIT_DIR / f"{tag(source)}{split}_sample_round{audit_round}.json"


def page_path(split: str, source: str = "gsu") -> Path:
    name = "audit.html" if split == "dev" else f"audit_{split}.html"
    return PAGE.with_name(tag(source) + name)


def audit_round(cfg: dict[str, Any], split: str, source: str = "gsu") -> int:
    """GSU rounds come from config (A1); each A2 source has one round per split."""
    if source != "gsu":
        return 1
    return cfg["audit"]["round"] if split == "dev" else cfg["audit"]["test_round"]


def build_page(
    records: list[dict[str, Any]], cfg: dict[str, Any], split: str = "dev", source: str = "gsu"
) -> str:
    """Draw the sample from `records` and write the check page. Returns a one-line summary.

    For the test split the caller passes the records it has just made, so no file
    under eval/gold/test/ is opened, and the committed sample holds ids only."""
    dates = sorted({r["report_date"] for r in records})
    texts = {
        f"{source}-{d}": (DATA / "text" / source / f"{d}.txt").read_text(encoding="utf-8")
        for d in dates
    }
    aid_dir = DATA / "text" / f"{source}_en"
    aids = {f"{source}-{d}": load_translation(d, aid_dir) for d in dates}
    counts = {rid: len(paragraph_spans(t)) for rid, t in texts.items()}
    a = cfg["audit"]
    n = audit_round(cfg, split, source)
    seed = cfg["eval"]["seed"] + n - 1
    if split == "dev" and source == "gsu":
        size = round_sizes(cfg, n)
        skip = earlier_draws(records, counts, cfg, size["skip_rounds"])
        sample = draw(records, counts, size["events"], size["paragraphs"], seed, skip)
    else:
        sample = draw(records, counts, a["events"], a["paragraphs"], seed)
    page = page_path(split, source)
    page.parent.mkdir(parents=True, exist_ok=True)
    items = build_items(sample, records, texts, aids)
    page.write_text(render_page(items, TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8")
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    if split == "dev":
        public = [committable(s, records) for s in sample]
    else:
        public = [{"id": s["id"], "kind": s["kind"]} for s in sample]
    sample_path(n, split, source).write_text(json.dumps(public, indent=1), encoding="utf-8")
    n_events = sum(s["kind"] == "event" for s in sample)
    return (
        f"{split} round {n}: {n_events} events and {len(sample) - n_events} paragraphs "
        f"-> {page.relative_to(ROOT)}"
    )


def build(cfg: dict[str, Any], source: str = "gsu") -> None:
    records = read_key(source=source)
    if not records:
        raise SystemExit(f"no machine-made {source} key in eval/gold/dev/; run the reviewer first")
    print(build_page(records, cfg, "dev", source))


def report(
    cfg: dict[str, Any], answers_path: Path, split: str = "dev", source: str = "gsu"
) -> None:
    n = audit_round(cfg, split, source)
    sample = json.loads(sample_path(n, split, source).read_text(encoding="utf-8"))
    answers = clean_answers(json.loads(answers_path.read_text(encoding="utf-8")))
    public = answers
    if split == "test":  # notes may quote the reports: keep them local, commit verdicts only
        public = {k: {"verdict": v["verdict"]} for k, v in answers.items()}
        notes = page_path(split, source).with_name(f"{tag(source)}{split}_notes_round{n}.json")
        notes.write_text(json.dumps(answers, ensure_ascii=False, indent=1), encoding="utf-8")
    (AUDIT_DIR / f"{tag(source)}{split}_answers_round{n}.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    limit = cfg["audit"]["max_error_rate"]
    result = score(sample, answers)
    for kind, res in result.items():
        ok = res["rate"] is not None and res["rate"] <= limit and not res["unanswered"]
        print(f"{kind}: {res} -> {'OK' if ok else 'NOT ACCEPTED'} (limit {limit})")
    earlier = round_sizes(cfg, n)["skip_rounds"] if split == "dev" and source == "gsu" else []
    if earlier:
        results = [result]
        for m in earlier:
            old_sample = json.loads(sample_path(m).read_text(encoding="utf-8"))
            old = json.loads((AUDIT_DIR / f"dev_answers_round{m}.json").read_text(encoding="utf-8"))
            results.append(score(old_sample, old))
        for kind, res in pooled(results).items():
            print(f"rounds {earlier + [n]} together, {kind}: {res}")
    for item_id, a in answers.items():
        if a["verdict"] in ("wrong", "missing", "unsure"):
            print(f"  {item_id}: {a['verdict']} {a['note']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    bd = sub.add_parser("build")
    bd.add_argument("--source", choices=["gsu", "af", "rumod"], default="gsu")
    sc = sub.add_parser("score")
    sc.add_argument("answers", type=Path)
    sc.add_argument("--split", choices=["dev", "test"], default="dev")
    sc.add_argument("--source", choices=["gsu", "af", "rumod"], default="gsu")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.cmd == "build":
        build(cfg, args.source)
    else:
        report(cfg, args.answers, args.split, args.source)


if __name__ == "__main__":
    main()
