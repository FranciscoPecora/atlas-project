"""Schema-constrained extraction (pipeline step 2, system S1; SPEC.md section 6).

    uv run python -m src.extract            # dev General Staff reports, config effort
    uv run python -m src.extract --alt      # same, with models.extraction_effort_alt

One call per section. The prompt holds fixed instructions and worked examples
first (so the API can cache them), then the report date, section name and
section text. The model returns events with an `evidence_quote`; it never
returns offsets or coordinates. Code finds the quote to get offsets.

Worked examples are not stored in the repository: they are built at run time
from paragraphs of one dev report (config `extract.example_report`), taking the
events from the dev answer key and the quotes from the local text. That report
is therefore not a fair test of the extractor; scores are also reported without it.

Raw model output goes to data/pred/ (git-ignored: it holds quoted source text).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

from src.collect import DATA, ROOT
from src.config import config_hash, load_config
from src.labels import GOLD, SPEC, gold_units
from src.prelabel import event_date, paragraph_spans
from src.review import GUIDELINE, guideline_rules, unit_task_data, with_retries
from src.schema import ExtractionResult
from src.verify_det import find_quote

SYSTEM = "S1"
PRED = DATA / "pred"
MODEL_FIELDS = (
    "event_type", "epistemic_status", "claim_source", "actor", "target", "location_text",
    "geo_precision", "event_date", "quantity", "evidence_quote",
)  # fmt: skip

TASK = (
    "You extract battlefield events from one section of a daily military report. "
    "Follow the annotation guideline below exactly; it is the standard your output "
    "is scored against.\n\n"
    "Rules that matter most:\n"
    "- One event per place per day. A sentence naming three places is three events "
    "that share one evidence_quote.\n"
    "- evidence_quote is an exact, contiguous copy of text from the section. Do not "
    "translate it, shorten it with dots or fix its spelling.\n"
    "- location_text is the place name exactly as written inside evidence_quote, in "
    "the same grammatical form. Use null when the text names no place. Never guess one.\n"
    "- quantity is filled only when the quote gives a number that counts this one "
    "event. A total shared by several places belongs to none of them: use null.\n"
    "- event_date: use the date the text gives. If it gives none, use the default "
    "date stated with the section.\n"
    "- A section with no events returns an empty list.\n"
    "- Use event type other, and null fields, when the text does not say.\n"
)


def instructions(guideline: str) -> str:
    return TASK + "\n# Annotation guideline\n\n" + guideline_rules(guideline)


def user_prompt(report_date: str, default_date: str, section: str, text: str) -> str:
    return (
        f"Report date: {report_date}\n"
        f"Default event date (when the text gives none): {default_date}\n"
        f"Section: {section}\n"
        f"Section text:\n{text}"
    )


def example_events(gold: list[dict[str, Any]], text: str, a: int, b: int) -> list[dict[str, Any]]:
    """Answer-key events whose evidence lies in text[a:b], in the model's output shape."""
    inside = [g for g in gold if a <= g["evidence_start"] < b]
    return [
        {**{f: g.get(f) for f in MODEL_FIELDS[:-1]},
         "evidence_quote": text[g["evidence_start"] : g["evidence_end"]]}
        for g in inside
    ]  # fmt: skip


def examples_block(
    text: str, gold: list[dict[str, Any]], paragraphs: list[int], report_date: str, default: str
) -> str:
    """Worked examples: one paragraph each, followed by the events the key holds for it."""
    spans = paragraph_spans(text)
    parts = []
    for n, p in enumerate(paragraphs, 1):
        a, b = spans[p - 1]
        answer = {"events": example_events(gold, text, a, b)}
        parts.append(
            f"## Example {n}\n{user_prompt(report_date, default, 'FULL', text[a:b])}\n"
            f"Output:\n{json.dumps(answer, ensure_ascii=False)}"
        )
    return "# Worked examples\n\n" + "\n\n".join(parts)


def load_examples(cfg: dict[str, Any], limit: int | None = None) -> str:
    """The worked examples named in config, built from dev gold and local text."""
    day = str(cfg["extract"]["example_report"])
    paragraphs = cfg["extract"]["example_paragraphs"][:limit]
    data = unit_task_data(day, SPEC.read_text(encoding="utf-8"))  # raises on a test report
    text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
    path = GOLD / "dev" / f"gsu-{day}__FULL__pass1.jsonl"
    gold = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return examples_block(text, gold, paragraphs, day, default_date(data))


def default_date(data: dict[str, Any]) -> str:
    """SPEC section 1: GSU reports describe the previous day; ISW uses the report date."""
    return event_date(data["report_date"]) if data["source"] == "gsu" else data["report_date"]


def usage_dict(usage: Any) -> dict[str, int]:
    """Token counts from the API response, with missing fields as 0."""
    names = ("input_tokens", "output_tokens")
    names += ("cache_creation_input_tokens", "cache_read_input_tokens")
    return {n: int(getattr(usage, n, 0) or 0) for n in names}


def cost_usd(usage: dict[str, int], price: dict[str, float]) -> float:
    """Dollars for one call. Prices are per million tokens (config.yaml `prices`)."""
    return (
        usage["input_tokens"] * price["input"]
        + usage["output_tokens"] * price["output"]
        + usage["cache_creation_input_tokens"] * price["cache_write"]
        + usage["cache_read_input_tokens"] * price["cache_read"]
    ) / 1_000_000


def extract_section(
    client: Any, cfg: dict[str, Any], system: str, user: str, effort: str
) -> tuple[ExtractionResult, dict[str, int], float]:
    """One structured call. Returns the parsed events, token usage and wall-clock seconds."""
    started = time.monotonic()
    response = client.beta.messages.parse(
        model=cfg["models"]["extraction"],
        max_tokens=cfg["extract"]["max_tokens"],
        timeout=cfg["extract"]["timeout_seconds"],
        output_config={"effort": effort},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=ExtractionResult,
    )
    seconds = time.monotonic() - started
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"extraction stopped: {response.stop_reason}")
    return response.parsed_output, usage_dict(response.usage), seconds


def to_records(
    events: list[dict[str, Any]], text: str, data: dict[str, Any], system: str
) -> list[dict[str, Any]]:
    """Scorable records for a system WITHOUT verification: nothing is rejected.

    Offsets are filled in when the quote is found (the geocoder uses them to
    read the paragraph's front direction) and left None when it is not.
    """
    records = []
    for i, e in enumerate(events):
        found = find_quote(str(e.get("evidence_quote") or ""), text)
        records.append(
            {
                **e,
                "id": f"{data['report_id']}:{system}:{i}",
                "report_id": data["report_id"],
                "source": data["source"],
                "report_date": data["report_date"],
                "sector": data["sector"],
                "evidence_start": found[0] if found else None,
                "evidence_end": found[1] if found else None,
                "system": system,
            }
        )
    return records


def pred_path(system: str, report_id: str, pred_dir: Path = PRED) -> Path:
    return pred_dir / system / f"{report_id}.json"


def write_pred(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def read_pred(system: str, report_id: str, pred_dir: Path = PRED) -> dict[str, Any] | None:
    path = pred_path(system, report_id, pred_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def dev_gsu_dates(spec_text: str, data_dir: Path = DATA) -> list[str]:
    """Dates of the dev General Staff gold reports that are collected."""
    days = [
        u.report_date.isoformat()
        for u in gold_units(spec_text)
        if u.split == "dev" and u.source.lower() == "gsu"
    ]
    return [d for d in days if (data_dir / "text" / "gsu" / f"{d}.txt").exists()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--alt", action="store_true", help="use models.extraction_effort_alt")
    args = ap.parse_args(argv)

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    models = cfg["models"]
    effort = models["extraction_effort_alt"] if args.alt else models["extraction_effort"]
    name = f"{SYSTEM}-{effort}" if args.alt else SYSTEM
    spec_text = SPEC.read_text(encoding="utf-8")
    system = instructions(GUIDELINE.read_text(encoding="utf-8")) + "\n\n" + load_examples(cfg)
    client = anthropic.Anthropic()
    price = cfg["prices"][models["extraction"]]
    for day in dev_gsu_dates(spec_text):
        data = unit_task_data(day, spec_text)  # refuses test-split reports
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        user = user_prompt(day, default_date(data), data["sector"], text)
        result, usage, seconds = with_retries(
            lambda user=user: extract_section(client, cfg, system, user, effort)
        )
        events = [e.model_dump(mode="json") for e in result.events]
        write_pred(
            pred_path(name, data["report_id"]),
            {
                "report_id": data["report_id"],
                "system": name,
                "model": models["extraction"],
                "effort": effort,
                "config_hash": config_hash(cfg),
                "seconds": round(seconds, 2),
                "usage": usage,
                "cost_usd": cost_usd(usage, price),
                "events": events,
            },
        )
        print(f"{name} {day}: {len(events)} events, {seconds:.1f} s, "
              f"${cost_usd(usage, price):.5f}, tokens {usage}")  # fmt: skip


if __name__ == "__main__":
    main()
