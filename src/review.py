"""Reviewer model: turns rule pre-fills into a draft answer key for GSU dev reports.

    uv run python -m src.review 2026-07-21 [...] [--force]   # dev reports
    uv run python -m src.review --split test                # the test key, once

Step 2 of amendment A1 (docs/spec_amendment_A1.md). The reviewer
reads the Ukrainian report, the annotation guideline and the rule pre-fills
(src/prelabel.py), and returns the final list of events. Code then finds each
quote in the report to get offsets, and rejects any event whose quote, place or
quantity is not in the text. The key is spot-checked by a person (src/audit.py).

The test key is made once for all collected test reports (--split test); the
run also builds its spot-check page, so the test files are never read back.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.collect import DATA, ROOT
from src.config import load_config
from src.labels import GOLD, SPEC, event_record, gold_units, make_tasks
from src.prelabel import (
    CLAIM_SOURCE,
    NUMBER,
    VERSION,
    Prefill,
    event_date,
    paragraph_spans,
    prefill_report,
    to_int,
)
from src.schema import EpistemicStatus, EventType, Side

METHOD = "rules+review-v1"
GUIDELINE = ROOT / "docs" / "annotation_guideline.md"

SYSTEM = (
    "You are the second annotator of a battlefield event dataset. You read daily "
    "reports of the Ukrainian General Staff in Ukrainian and apply the annotation "
    "guideline below exactly. A rule-based program has drafted events; it only "
    "knows one sentence pattern, so it misses front-wide totals, mislabels "
    "shelling and air strikes as ground assaults, and cannot see a second event "
    "at the same place. Return the final, complete list of events: keep correct "
    "drafts, correct wrong fields, leave out drafts that are not events, and add "
    "every event the draft missed. Copy evidence_quote and location_text from "
    "the paragraph character for character; never translate or re-inflect them. "
    "Set quantity only when that number is written inside your evidence_quote "
    "and counts that one event.\n\n"
)


class ReviewedEvent(BaseModel):
    paragraph: int = Field(description="Number of the paragraph the evidence is in")
    event_type: EventType
    epistemic_status: EpistemicStatus
    actor: Side | None
    target: Side | None
    location_text: str | None = Field(description="Place exactly as written in evidence_quote")
    geo_precision: int | None = Field(description="1, 2 or 3 as in the guideline; null if no place")
    quantity: int | None
    evidence_quote: str = Field(description="Exact contiguous text copied from the paragraph")


class Review(BaseModel):
    events: list[ReviewedEvent]


class RefusedTestSplit(RuntimeError):
    pass


def guideline_rules(text: str) -> str:
    """Guideline sections 1 to 7 and 9 (rules and rulings), without the procedure."""
    head, rest = text.split("\n## 8.", 1)
    hard = rest.split("\n## 9.", 1)[1].split("\n## 10.", 1)[0]
    return head.strip() + "\n\n## 9." + hard.rstrip()


def describe(p: Prefill) -> str:
    qty = "none" if p.quantity is None else str(p.quantity)
    return f"{p.event_type} | place: {p.location_text or 'none'} | quantity: {qty}"


def build_prompt(text: str, prefills: list[Prefill]) -> str:
    parts = []
    for i, (a, b) in enumerate(paragraph_spans(text), start=1):
        drafts = [describe(p) for p in prefills if a <= p.start and p.end <= b]
        listed = "\n".join(f"  draft: {d}" for d in drafts) or "  draft: (nothing)"
        parts.append(f"[{i}] {text[a:b]}\n{listed}")
    return (
        "Below is one report as numbered paragraphs. Under each paragraph are the "
        "events the rule-based program drafted from it. Every draft has status "
        "ua_claimed, actor RU, target UA and precision 2; change these where the "
        "guideline says otherwise. Return the final events for the whole report.\n\n"
        + "\n\n".join(parts)
    )


def has_quantity(quote: str, quantity: int) -> bool:
    """SPEC 2.2: the number is in the quote, as digits or as a number word."""
    return any(to_int(tok) == quantity for tok in re.findall(NUMBER, quote))


def to_records(
    review: Review, text: str, data: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Gold records with code-computed offsets, plus the events rejected by the checks."""
    paras = paragraph_spans(text)
    day = event_date(data["report_date"])
    records: list[dict[str, Any]] = []
    rejected: list[str] = []
    for e in review.events:
        label = f"[{e.paragraph}] {e.event_type.value} {e.location_text or '-'}"
        if not 1 <= e.paragraph <= len(paras):
            rejected.append(f"{label}: no such paragraph")
            continue
        a, b = paras[e.paragraph - 1]
        at = text.find(e.evidence_quote, a, b)
        if at < 0:
            rejected.append(f"{label}: quote is not in the paragraph")
        elif e.location_text and e.location_text not in e.evidence_quote:
            rejected.append(f"{label}: place is not in the quote")
        elif e.quantity is not None and not has_quantity(e.evidence_quote, e.quantity):
            rejected.append(f"{label}: quantity {e.quantity} is not in the quote")
        else:
            fields = e.model_dump(mode="json", exclude={"paragraph"})
            fields.update(claim_source=CLAIM_SOURCE, event_date=day)
            records.append(event_record(fields, data, at))
    records.sort(key=lambda r: (r["evidence_start"], r["evidence_end"]))
    return records, rejected


def review_report(client: Any, models: dict[str, Any], text: str, guideline: str) -> Review:
    response = client.beta.messages.parse(
        model=models["gold_review"],
        max_tokens=32000,
        timeout=900,  # explicit: the SDK refuses large non-streaming calls otherwise
        output_config={"effort": models["gold_review_effort"]},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM + guideline_rules(guideline),
        messages=[{"role": "user", "content": build_prompt(text, prefill_report(text))}],
        output_format=Review,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"review stopped: {response.stop_reason}")
    return response.parsed_output


def unit_task_data(
    report_date: str, spec_text: str, data_dir: Path = DATA, split: str = "dev"
) -> dict[str, Any]:
    """Task data (ids, hash, URL) of a GSU gold unit of `split`. A test unit is given
    only when test is asked for by name; unknown dates are refused."""
    day = date.fromisoformat(report_date)
    unit = next(
        (u for u in gold_units(spec_text) if u.source == "gsu" and u.report_date == day), None
    )
    if unit is None:
        raise ValueError(f"gsu-{report_date} is not a gold unit in SPEC.md section 4.2")
    if unit.split != split:
        raise RefusedTestSplit(
            f"gsu-{report_date} is a {unit.split} unit, but this run is for {split}; the test "
            "key is made once, with --split test (SPEC.md amendment A1)"
        )
    tasks, missing = make_tasks([unit], data_dir)
    if missing:
        raise FileNotFoundError(f"gsu-{report_date} is not collected yet")
    return tasks[0]["data"]


def gold_path(report_date: str, gold_dir: Path = GOLD, split: str = "dev") -> Path:
    return gold_dir / split / f"gsu-{report_date}__FULL__pass1.jsonl"


def is_human_labelled(path: Path) -> bool:
    if not path.exists():
        return False
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return any(r.get("label_method") != METHOD for r in lines)


def write_gold(path: Path, records: list[dict[str, Any]], model: str) -> None:
    for r in records:
        r.update(annotation_pass=1, minutes=None, prelabel=VERSION, label_method=METHOD)
        r["reviewer"] = model
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def ensure_translation(client: Any, models: dict[str, Any], day: str, text: str) -> None:
    """English reading aid for the spot check, made once per report (cached on disk)."""
    from src.translate import load_translation, paragraphs, translate, write_translation

    if load_translation(day) is None:
        result = translate(client, models, text)
        write_translation(day, result, paragraphs(text), models["translation"])


def with_retries(call: Any, attempts: int = 3) -> Any:
    """Run `call`, trying again after an API or validation error."""
    for n in range(attempts):
        try:
            return call()
        except (anthropic.APIError, RuntimeError, ValueError):
            if n == attempts - 1:
                raise
    return None


def gsu_test_dates(spec_text: str, data_dir: Path = DATA) -> tuple[list[str], list[str]]:
    """GSU test units of the rotation table: (collected dates, missing dates)."""
    days = [
        u.report_date.isoformat()
        for u in gold_units(spec_text)
        if u.source == "gsu" and u.split == "test"
    ]
    have = [d for d in days if (data_dir / "text" / "gsu" / f"{d}.txt").exists()]
    return have, [d for d in days if d not in have]


def make_test_key(client: Any, cfg: dict[str, Any], spec_text: str, guideline: str) -> None:
    """Amendment A1, test split: review every collected GSU test report once, write the
    key, and build the spot-check page from the records in memory. Nothing under
    eval/gold/test/ is read, and only counts are printed."""
    from src.audit import build_page

    models = cfg["models"]
    dates, missing = gsu_test_dates(spec_text)
    paths = {d: gold_path(d, split="test") for d in dates}
    if any(p.exists() for p in paths.values()):
        raise SystemExit("a GSU test key already exists; it is made once (amendment A1)")
    made: dict[str, list[dict[str, Any]]] = {}
    for day in dates:  # everything stays in memory until every report has succeeded
        data = unit_task_data(day, spec_text, split="test")
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        ensure_translation(client, models, day, text)
        review = with_retries(lambda t=text: review_report(client, models, t, guideline))
        made[day], rejected = to_records(review, text, data)
        print(f"{day}: {len(made[day])} events, {len(rejected)} rejected by checks", flush=True)
    for day, records in made.items():
        write_gold(paths[day], records, models["gold_review"])
    everything = [r for records in made.values() for r in records]
    print(f"test units not collected: {', '.join(missing) or '-'}")
    print(build_page(everything, cfg, "test"))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dates", nargs="*", help="dev report dates, YYYY-MM-DD")
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--force", action="store_true", help="review again if a key exists")
    args = ap.parse_args(argv)

    load_dotenv(ROOT / ".env")
    models = load_config()["models"]
    spec_text = SPEC.read_text(encoding="utf-8")
    guideline = GUIDELINE.read_text(encoding="utf-8")
    client = anthropic.Anthropic()
    if args.split == "test":
        make_test_key(client, load_config(), spec_text, guideline)
        return
    for day in args.dates:
        data = unit_task_data(day, spec_text)
        path = gold_path(day)
        if is_human_labelled(path):
            raise SystemExit(f"{path.name} holds hand-made labels; not overwriting")
        if path.exists() and not args.force:
            print(f"{day}: already reviewed, skipped (use --force)")
            continue
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        records, rejected = to_records(review_report(client, models, text, guideline), text, data)
        write_gold(path, records, models["gold_review"])
        print(
            f"{day}: {len(prefill_report(text))} rule drafts -> {len(records)} events kept, "
            f"{len(rejected)} rejected by checks -> {path.relative_to(ROOT)}"
        )
        for r in rejected:
            print(f"  rejected {r}")


if __name__ == "__main__":
    main()
