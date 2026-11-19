"""Reviewer model for the A2 sources (AF, RUMOD): a draft answer key with no rule pre-fill.

    uv run python -m src.review_a2 --source af                # the 3 dev reports
    uv run python -m src.review_a2 --source af --split test   # the test key, once

Amendment A2 (docs/spec_amendment_A2.md) applies the A1 method without its first step:
the reviewer model (config `models.gold_review`) reads the report and the guideline
(sections 1 to 7, 8.4 and 9) and lists every event; code finds each quote in its
paragraph to get offsets, and rejects any event whose quote, place or quantity is not
in the text, or whose quote touches a RUMOD post-URL line. The owner spot-checks the key
(src/audit.py --source). The test key is made once, before any evaluated system runs on
those reports, and its check page is built from the records in memory: nothing under
eval/gold/test/ is read back.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

from src.collect import DATA, ROOT, read_manifest
from src.config import load_config
from src.labels import GOLD, event_record
from src.prelabel import paragraph_spans
from src.review import GUIDELINE, Review, has_quantity, with_retries
from src.sources import A2_SOURCES, a2_units, post_url_at, report_id, text_path

METHOD = "review-a2-v1"
CLAIM_SOURCE = {"af": "Ukrainian Air Force", "rumod": "Russian Ministry of Defence"}
DESCRIBE = {
    "af": "the Ukrainian Air Force's report on the overnight air attack, in Ukrainian",
    "rumod": (
        "one day of posts from the Russian Ministry of Defence's Telegram channel, in "
        "Russian; each post starts with a '## <url>' line that is never part of a quote"
    ),
}


def system_prompt(source: str) -> str:
    return (
        "You are the second annotator of a battlefield event dataset. You read "
        f"{DESCRIBE[source]}, and apply the annotation guideline below exactly, "
        "including section 8.4 for this source. Return the complete list of events. "
        "Copy evidence_quote and location_text from the paragraph character for "
        "character; never translate or re-inflect them. Set quantity only when that "
        "number is written inside your evidence_quote and counts that one event.\n\n"
    )


def guideline_rules_a2(text: str) -> str:
    """Guideline sections 1 to 7, 8.4 (the A2 sources) and 9, without the procedure."""
    head, rest = text.split("\n## 8.", 1)
    a2 = "### 8.4" + rest.split("\n### 8.4", 1)[1].split("\n## 9.", 1)[0]
    hard = rest.split("\n## 9.", 1)[1].split("\n## 10.", 1)[0]
    return head.strip() + "\n\n" + a2.rstrip() + "\n\n## 9." + hard.rstrip()


def build_prompt(text: str) -> str:
    parts = [f"[{i}] {text[a:b]}" for i, (a, b) in enumerate(paragraph_spans(text), start=1)]
    return (
        "Below is one report as numbered paragraphs. Return every event in it, with "
        "the number of the paragraph its evidence is in.\n\n" + "\n\n".join(parts)
    )


def report_data(source: str, day: str, split: str, data_dir: Path = DATA) -> dict[str, Any]:
    """Ids, hash and URL of a collected report, from the manifest."""
    rows = {(r["date"], r["source"]): r for r in read_manifest(data_dir / "manifest.csv")}
    m = rows.get((day, source))
    if m is None or m["status"] != "ok" or not text_path(source, day, data_dir).exists():
        raise FileNotFoundError(f"{report_id(source, day)} is not collected")
    return {"report_id": report_id(source, day), "source": source, "report_date": day,
            "sector": "FULL", "split": split, "text_sha256": m["sha256"],
            "source_url": m["url"]}  # fmt: skip


def to_records(
    review: Review, text: str, data: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Gold records with code-computed offsets, plus the events rejected by the checks."""
    paras = paragraph_spans(text)
    source = data["source"]
    records: list[dict[str, Any]] = []
    rejected: list[str] = []
    for e in review.events:
        label = f"[{e.paragraph}] {e.event_type.value} {e.location_text or '-'}"
        if not 1 <= e.paragraph <= len(paras):
            rejected.append(f"{label}: no such paragraph")
            continue
        a, b = paras[e.paragraph - 1]
        at = text.find(e.evidence_quote, a, b) if e.evidence_quote.strip() else -1
        if at < 0:
            rejected.append(f"{label}: quote is not in the paragraph")
        elif "## http" in e.evidence_quote or "t.me/" in e.evidence_quote:
            rejected.append(f"{label}: quote holds a post-URL line")
        elif e.location_text and e.location_text not in e.evidence_quote:
            rejected.append(f"{label}: place is not in the quote")
        elif e.quantity is not None and not has_quantity(e.evidence_quote, e.quantity):
            rejected.append(f"{label}: quantity {e.quantity} is not in the quote")
        else:
            fields = e.model_dump(mode="json", exclude={"paragraph"})
            fields.update(claim_source=CLAIM_SOURCE[source], event_date=data["report_date"])
            record = event_record(fields, data, at)
            if source == "rumod":
                record["source_url"] = post_url_at(text, at) or data["source_url"]
            records.append(record)
    records.sort(key=lambda r: (r["evidence_start"], r["evidence_end"]))
    return records, rejected


def review_report(client: Any, models: dict[str, Any], source: str, text: str,
                  guideline: str) -> Review:  # fmt: skip
    response = client.beta.messages.parse(
        model=models["gold_review"],
        max_tokens=32000,
        timeout=900,
        output_config={"effort": models["gold_review_effort"]},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system_prompt(source) + guideline_rules_a2(guideline),
        messages=[{"role": "user", "content": build_prompt(text)}],
        output_format=Review,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"review stopped: {response.stop_reason}")
    return response.parsed_output


def gold_path(source: str, day: str, split: str, gold_dir: Path = GOLD) -> Path:
    return gold_dir / split / f"{report_id(source, day)}__FULL__pass1.jsonl"


def save(path: Path, records: list[dict[str, Any]], model: str) -> None:
    """Write a gold file in A1's format, marked as an A2 key with no rule pre-fill."""
    for r in records:
        r.update(annotation_pass=1, minutes=None, prelabel=None, label_method=METHOD,
                 reviewer=model)  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def ensure_translation(client: Any, models: dict[str, Any], source: str, day: str,
                       text: str) -> None:  # fmt: skip
    """English reading aid for the spot check, once per report, in data/text/<source>_en/."""
    from src.translate import load_translation, paragraphs, translate, write_translation

    out = DATA / "text" / f"{source}_en"
    if load_translation(day, out) is None:
        result = with_retries(lambda: translate(client, models, text))
        write_translation(day, result, paragraphs(text), models["translation"], out)


def make_key(client: Any, cfg: dict[str, Any], source: str, split: str, guideline: str,
             force: bool = False) -> None:  # fmt: skip
    """Review every collected unit of one split. The test key is made once."""
    from src.audit import build_page

    models = cfg["models"]
    units = [(d, s) for d, s in a2_units(source, cfg) if s == split]
    have = [d for d, _ in units if text_path(source, d).exists()]
    missing = [d for d, _ in units if d not in have]
    paths = {d: gold_path(source, d, split) for d in have}
    if split == "test" and any(p.exists() for p in paths.values()):
        raise SystemExit(f"a {source} test key already exists; it is made once (amendment A2)")
    made: dict[str, list[dict[str, Any]]] = {}
    for day in have:
        if split == "dev" and paths[day].exists() and not force:
            print(f"{day}: already reviewed, skipped (use --force)")
            continue
        text = text_path(source, day).read_text(encoding="utf-8")
        data = report_data(source, day, split)
        ensure_translation(client, models, source, day, text)
        review = with_retries(lambda t=text: review_report(client, models, source, t, guideline))
        made[day], rejected = to_records(review, text, data)
        print(f"{day}: {len(made[day])} events, {len(rejected)} rejected by checks", flush=True)
        if split == "dev":
            for r in rejected:
                print(f"  rejected {r}")
    for day, records in made.items():  # test: written only after every report succeeded
        save(paths[day], records, models["gold_review"])
    print(f"{source} {split} units not collected: {', '.join(missing) or '-'}")
    if split == "test" and made:
        everything = [r for records in made.values() for r in records]
        print(build_page(everything, cfg, "test", source))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=A2_SOURCES, required=True)
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--force", action="store_true", help="review dev reports again")
    args = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    guideline = GUIDELINE.read_text(encoding="utf-8")
    make_key(anthropic.Anthropic(), cfg, args.source, args.split, guideline, args.force)


if __name__ == "__main__":
    main()
