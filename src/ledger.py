"""Full-corpus run and the ledger (milestone 5, step 1).

    uv run python -m src.ledger run      # batches, geocoder, then data/ledger.parquet
    uv run python -m src.ledger build    # only rebuild data/ledger.parquet from saved runs

Stages, each resumable (a report already in data/pred/ is skipped, a submitted batch
is reused):

1. extract: S1 on every collected report without an S1 run, and B2 on the test
   reports. One Message Batches request per report.
2. verify: the shipped verifier (config `ledger.system`) on every report, and the
   other S3 variant on the test reports. One request per distinct evidence quote.
3. geocode: the S3 geocoder; names the rules cannot settle go to the model live
   (few calls, cached in data/pred/geocode_choices.json).
4. build: S3 records with offsets, coordinates and unit ids, validated as
   `LedgerEvent`, written to data/ledger.parquet (git-ignored: it holds
   `evidence_quote`; the public export in milestone 6 drops it).

Batch requests carry the same model, effort, system prompt and output schema as the
live calls in src/extract.py, src/baselines/b2_single_prompt.py and
src/verify_model.py. One difference: the Batches API refuses the `fallbacks`
parameter, so the batch calls send none (Haiku has no server-side fallback anyway).
Batch runs record `seconds: null`: speed is measured on live calls only (SPEC 5.3).
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
import polars as pl
from anthropic.lib._parse._transform import merge_output_config, to_json_output_format
from dotenv import load_dotenv
from pydantic import BaseModel

from src.batch import custom_id, reply_text
from src.batch import run as run_batch
from src.collect import DATA, ROOT
from src.config import config_hash, load_config
from src.extract import (
    cost_usd,
    default_date,
    instructions,
    load_examples,
    pred_path,
    read_pred,
    usage_dict,
    user_prompt,
    write_pred,
)
from src.labels import SPEC
from src.review import GUIDELINE, gsu_test_dates
from src.schema import ExtractionResult, LedgerEvent

LEDGER = DATA / "ledger.parquet"
MANIFEST = DATA / "manifest.csv"
VERIFIER_KEY = {"S3-H": "verifier", "S3-S": "verifier_alt"}


def corpus_days(cfg: dict[str, Any], data_dir: Path = DATA) -> list[str]:
    """Dates of the collected GSU reports inside the corpus window, in order."""
    start, end = str(cfg["corpus"]["start"]), str(cfg["corpus"]["end"])
    days = [p.stem for p in (data_dir / "text" / "gsu").glob("*.txt")]
    return sorted(d for d in days if start <= d <= end)


def report_text(day: str, data_dir: Path = DATA) -> str:
    return (data_dir / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")


def facts(day: str) -> dict[str, str]:
    return {"source": "gsu", "report_date": day,
            "default_date": default_date({"source": "gsu", "report_date": day})}  # fmt: skip


def structured_params(
    model: str, max_tokens: int, effort: str, system: str, user: str, fmt: type[BaseModel] | None
) -> dict[str, Any]:
    """Messages API parameters for one batch request; `fmt` adds the JSON output schema.

    The schema is produced by the SDK's own converter, the one `messages.parse` uses,
    so batch and live calls send the same output format.
    """
    output_config: dict[str, Any] = {"effort": effort}
    if fmt is not None:
        output_config = dict(merge_output_config(output_config, to_json_output_format(fmt)))
    return {
        "model": model,
        "max_tokens": max_tokens,
        "output_config": output_config,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
    }


def parsed(message: Any, fmt: type[BaseModel]) -> BaseModel:
    """The validated structured reply; raises if the model did not finish."""
    if message.stop_reason != "end_turn":
        raise RuntimeError(f"stopped: {message.stop_reason}")
    return fmt.model_validate_json(reply_text(message))


def run_payload(
    system: str, report_id: str, model: str, effort: str, cfg: dict[str, Any], usage: dict,
    batch_name: str, **extra: Any,
) -> dict[str, Any]:  # fmt: skip
    """The saved-run record, in the shape of the live runs, priced at the batch rate."""
    price = cfg["prices"][model]
    return {
        "report_id": report_id, "system": system, "model": model, "effort": effort,
        "config_hash": config_hash(cfg), "seconds": None, "usage": usage,
        "cost_usd": cost_usd(usage, price) * cfg["batch"]["price_factor"],
        "batch": batch_name, **extra,
    }  # fmt: skip


# --- stage 1: extraction -------------------------------------------------------------


def extract_stage(client: Any, cfg: dict[str, Any], days: list[str], test_days: list[str]) -> None:
    from src.baselines.b2_single_prompt import ASK, parse_reply

    models = cfg["models"]
    model, effort = models["extraction"], models["extraction_effort"]
    rules = instructions(GUIDELINE.read_text(encoding="utf-8"))
    systems = {
        "S1": (rules + "\n\n" + load_examples(cfg), ExtractionResult, days),
        "B2": (rules + "\n\n" + load_examples(cfg, limit=1) + ASK, None, test_days),
    }
    requests, wanted = [], {}
    for name, (prompt, fmt, which) in systems.items():
        for day in which:
            if name == "B2" and "B2" not in cfg["ledger"]["test_only_systems"]:
                continue
            if read_pred(name, f"gsu-{day}") is not None:
                continue
            user = user_prompt(day, facts(day)["default_date"], "FULL", report_text(day))
            cid = custom_id(name, day)
            wanted[cid] = (name, day)
            params = structured_params(model, cfg["extract"]["max_tokens"], effort, prompt,
                                       user, fmt)  # fmt: skip
            requests.append({"custom_id": cid, "params": params})
    print(f"extract: {len(requests)} reports to run")
    label = f"extract-{config_hash(cfg)}"
    ok, failed = run_batch(client, label, requests, cfg["batch"]["poll_seconds"],
                           cfg["batch"]["retries"])  # fmt: skip
    for cid, message in ok.items():
        name, day = wanted[cid]
        usage = usage_dict(message.usage)
        if name == "S1":
            events = [e.model_dump(mode="json") for e in parsed(message, ExtractionResult).events]
            extra: dict[str, Any] = {"events": events}
        else:
            events, dropped = parse_reply(reply_text(message), facts(day)["default_date"])
            extra = {"dropped_items": dropped, "events": events}
        write_pred(
            pred_path(name, f"gsu-{day}"),
            run_payload(name, f"gsu-{day}", model, effort, cfg, usage, label, **extra),
        )
        print(f"{name} {day}: {len(events)} events")  # fmt: skip
    if failed:
        raise RuntimeError(f"extract: {len(failed)} requests failed after retries: {failed}")


# --- stage 2: model verification -----------------------------------------------------


def quote_prompts(records: list[dict[str, Any]], day: str) -> list[str]:
    """The verifier prompts for a report, one per distinct quote, in call order."""
    from src.verify_model import Verification, verify_report

    prompts: list[str] = []

    def capture(u: str) -> tuple[Any, dict[str, int], float]:
        prompts.append(u)
        return Verification(records=[]), {}, 0.0

    verify_report(capture, records, facts(day))
    return prompts


def verify_stage(client: Any, cfg: dict[str, Any], plan: dict[str, list[str]]) -> None:
    """`plan` maps an S3 variant to the report dates it runs on."""
    from src.verify_model import Verification, s2_records, verify_report
    from src.verify_model import instructions as v_instructions

    system = v_instructions(GUIDELINE.read_text(encoding="utf-8"))
    models = cfg["models"]
    effort = models["verifier_effort"]
    requests: list[dict[str, Any]] = []
    jobs: dict[tuple[str, str], tuple[list[dict[str, Any]], list[str]]] = {}
    for name, days in plan.items():
        model = models[VERIFIER_KEY[name]]
        for day in days:
            if read_pred(name, f"gsu-{day}") is not None:
                continue
            records = s2_records(f"gsu-{day}", report_text(day))
            prompts = quote_prompts(records, day)
            jobs[(name, day)] = (records, prompts)
            for n, u in enumerate(prompts):
                params = structured_params(model, cfg["verify"]["max_tokens"], effort, system,
                                           u, Verification)  # fmt: skip
                requests.append({"custom_id": custom_id(name, day, f"q{n:04d}"), "params": params})
    print(f"verify: {len(jobs)} reports, {len(requests)} quotes")
    label = f"verify-{config_hash(cfg)}"
    ok, failed = run_batch(client, label, requests, cfg["batch"]["poll_seconds"],
                           cfg["batch"]["retries"])  # fmt: skip
    for (name, day), (records, prompts) in jobs.items():
        model = models[VERIFIER_KEY[name]]
        answers: dict[str, tuple[Any, dict[str, int], float]] = {}
        usage: Counter[str] = Counter()
        missing = 0
        for n, u in enumerate(prompts):
            message = ok.get(custom_id(name, day, f"q{n:04d}"))
            try:
                result = parsed(message, Verification) if message else None
            except (RuntimeError, ValueError):
                result = None
            if message is not None:
                usage.update(usage_dict(message.usage))
            missing += result is None
            answers[u] = (result or Verification(records=[]), {}, 0.0)
        verdicts, run = verify_report(lambda u, a=answers: a[u], records, facts(day))
        total = {k: usage.get(k, 0) for k in usage_dict(object())}
        write_pred(pred_path(name, f"gsu-{day}"), run_payload(
            name, f"gsu-{day}", model, effort, cfg, total, label,
            n_records=len(records), verdicts=verdicts, reasons=run["reasons"],
            quotes_without_answer=missing,
        ))  # fmt: skip
        print(f"{name} {day}: {len(records)} records, {len(prompts)} quotes, {missing} unanswered")
    if failed:
        print(f"verify: {len(failed)} quotes failed after retries; their fields stay unjudged")


# --- stage 4: the ledger -------------------------------------------------------------


def manifest(path: Path = MANIFEST) -> dict[str, str]:
    """{report date: source url} for collected GSU reports."""
    rows = pl.read_csv(path, infer_schema_length=0).filter(
        (pl.col("source") == "gsu") & (pl.col("status") == "ok")
    )
    return dict(zip(rows["date"].to_list(), rows["url"].to_list(), strict=True))


def ledger_rows(
    records: list[dict[str, Any]], text: str, day: str, url: str, system: str, run_id: str,
    unit_table: list[dict[str, str]], fuzzy_min: float,
) -> list[dict[str, Any]]:  # fmt: skip
    """Geocoded S3 records of one report as validated ledger rows (JSON-ready dicts)."""
    from src.units import unit_ids

    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    rid = f"gsu-{day}"
    out = []
    fields = LedgerEvent.model_fields  # the schema forbids extra keys (geocode_how, ...)
    for i, r in enumerate(records):
        row = LedgerEvent.model_validate({
            **{k: v for k, v in r.items() if k in fields},
            "event_id": f"{rid}:{system}:{i}", "report_id": rid, "source": "gsu",
            "section": "FULL", "sector": "FULL", "report_date": day,
            "unit_ids": unit_ids(r.get("units") or [], unit_table, fuzzy_min),
            "text_sha256": sha, "source_url": url, "system": system, "run_id": run_id,
        })  # fmt: skip
        out.append(row.model_dump(mode="json"))
    return out


def build(cfg: dict[str, Any], days: list[str], out: Path = LEDGER) -> pl.DataFrame:
    """Assemble data/ledger.parquet from the saved S3 runs (no API call)."""
    from src.gazetteer import Gazetteer, read_table
    from src.geocode import cached_chooser
    from src.s3 import geocode_s3, load_choices, verified
    from src.units import read_table as read_units

    system = cfg["ledger"]["system"]
    gaz = Gazetteer(read_table())
    chooser = cached_chooser(load_choices())
    urls = manifest()
    units = read_units()
    run_id = f"{date.today().isoformat()}-{config_hash(cfg)}"
    rows: list[dict[str, Any]] = []
    for day in days:
        text = report_text(day)
        kept, _ = verified(system, f"gsu-{day}", text)
        located = geocode_s3(kept, text, day, gaz, cfg["geocode"], chooser)
        rows += ledger_rows(located, text, day, urls[day], system, run_id, units,
                            cfg["units"]["fuzzy_min"])  # fmt: skip
    frame = pl.DataFrame(rows, infer_schema_length=None)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out)
    return frame


def summary(frame: pl.DataFrame) -> str:
    """Counts worth printing after a build: rows, reports, located share, type x status."""
    located = frame["lat"].is_not_null().sum()
    lines = [
        f"{frame.height} events in {frame['report_id'].n_unique()} reports; "
        f"{located} located ({located / max(frame.height, 1):.1%})",
        str(frame.group_by("event_type", "epistemic_status").len().sort("len", descending=True)),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=["run", "build"])
    args = ap.parse_args(argv)
    cfg = load_config()
    days = corpus_days(cfg)
    test_days, _ = gsu_test_dates(SPEC.read_text(encoding="utf-8"))
    if args.stage == "run":
        from src.verify_model import geocode_choices

        load_dotenv(ROOT / ".env")
        client = anthropic.Anthropic()
        extract_stage(client, cfg, days, test_days)
        shipped = cfg["ledger"]["system"]
        plan = {shipped: days}
        plan.update({s: test_days for s in cfg["ledger"]["test_only_systems"] if s in VERIFIER_KEY})
        verify_stage(client, cfg, plan)
        for name, which in plan.items():
            geocode_choices(client, cfg, name, which)
    frame = build(cfg, days)
    print(summary(frame))
    print(f"wrote {LEDGER.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
