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
    pred_path,
    read_pred,
    system_prompt_for,
    usage_dict,
    user_prompt,
    write_pred,
)
from src.labels import SPEC
from src.review import GUIDELINE, gsu_test_dates
from src.schema import ExtractionResult, LedgerEvent
from src.sources import A2_SOURCES, a2_units, post_url_at, split_report_id, text_path

LEDGER = DATA / "ledger.parquet"
MANIFEST = DATA / "manifest.csv"
VERIFIER_KEY = {"S3-H": "verifier", "S3-S": "verifier_alt"}


def corpus_days(cfg: dict[str, Any], data_dir: Path = DATA, source: str = "gsu") -> list[str]:
    """Dates of a source's collected reports inside the corpus window, in order."""
    start, end = str(cfg["corpus"]["start"]), str(cfg["corpus"]["end"])
    days = [p.stem for p in (data_dir / "text" / source).glob("*.txt")]
    return sorted(d for d in days if start <= d <= end)


def corpus_reports(cfg: dict[str, Any], sources: list[str], data_dir: Path = DATA) -> list[str]:
    """Report ids ("af-2026-08-03") of the sources' collected reports, by source then date."""
    return [f"{s}-{d}" for s in sources for d in corpus_days(cfg, data_dir, s)]


def report_text(rid: str, data_dir: Path = DATA) -> str:
    source, day = split_report_id(rid)
    return text_path(source, day, data_dir).read_text(encoding="utf-8")


def facts(rid: str) -> dict[str, str]:
    source, day = split_report_id(rid)
    return {"source": source, "report_date": day,
            "default_date": default_date({"source": source, "report_date": day})}  # fmt: skip


def test_reports(cfg: dict[str, Any], sources: list[str], data_dir: Path = DATA) -> list[str]:
    """Collected test-split report ids of the sources (GSU: SPEC 4.2; AF, RUMOD: A2)."""
    out = []
    for source in sources:
        if source == "gsu":
            days, _ = gsu_test_dates(SPEC.read_text(encoding="utf-8"), data_dir)
        else:
            days = [d for d, split in a2_units(source, cfg) if split == "test"]
        out += [f"{source}-{d}" for d in days if text_path(source, d, data_dir).exists()]
    return out


def a2_key_ready(source: str, cfg: dict[str, Any], gold_dir: Path | None = None) -> bool:
    """A2: a source's test key must exist before any evaluated system runs on its reports.
    Checks that the files exist; never opens them."""
    from src.labels import GOLD
    from src.review_a2 import gold_path

    gold_dir = gold_dir or GOLD
    tests = [d for d, split in a2_units(source, cfg) if split == "test"]
    have = [d for d in tests if text_path(source, d).exists()]
    return bool(have) and all(gold_path(source, d, "test", gold_dir).exists() for d in have)


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


def extract_stage(client: Any, cfg: dict[str, Any], rids: list[str], test_rids: list[str]) -> None:
    from src.baselines.b2_single_prompt import ASK, parse_reply

    models = cfg["models"]
    model, effort = models["extraction"], models["extraction_effort"]
    guideline = GUIDELINE.read_text(encoding="utf-8")
    sources = sorted({split_report_id(r)[0] for r in rids + test_rids})
    s1 = {s: system_prompt_for(s, cfg, guideline) for s in sources}
    b2 = {s: system_prompt_for(s, cfg, guideline, limit=1) + ASK for s in sources}
    systems = {"S1": (s1, ExtractionResult, rids), "B2": (b2, None, test_rids)}
    requests, wanted = [], {}
    for name, (prompts, fmt, which) in systems.items():
        for rid in which:
            if name == "B2" and "B2" not in cfg["ledger"]["test_only_systems"]:
                continue
            if read_pred(name, rid) is not None:
                continue
            f = facts(rid)
            prompt = prompts[f["source"]]
            user = user_prompt(f["report_date"], f["default_date"], "FULL", report_text(rid))
            cid = custom_id(name, rid)
            wanted[cid] = (name, rid)
            params = structured_params(model, cfg["extract"]["max_tokens"], effort, prompt,
                                       user, fmt)  # fmt: skip
            requests.append({"custom_id": cid, "params": params})
    print(f"extract: {len(requests)} reports to run")
    label = f"extract-{config_hash(cfg)}"
    ok, failed = run_batch(client, label, requests, cfg["batch"]["poll_seconds"],
                           cfg["batch"]["retries"])  # fmt: skip
    for cid, message in ok.items():
        name, rid = wanted[cid]
        usage = usage_dict(message.usage)
        if name == "S1":
            events = [e.model_dump(mode="json") for e in parsed(message, ExtractionResult).events]
            extra: dict[str, Any] = {"events": events}
        else:
            events, dropped = parse_reply(reply_text(message), facts(rid)["default_date"])
            extra = {"dropped_items": dropped, "events": events}
        write_pred(
            pred_path(name, rid),
            run_payload(name, rid, model, effort, cfg, usage, label, **extra),
        )
        print(f"{name} {rid}: {len(events)} events")  # fmt: skip
    if failed:
        raise RuntimeError(f"extract: {len(failed)} requests failed after retries: {failed}")


# --- stage 2: model verification -----------------------------------------------------


def quote_prompts(records: list[dict[str, Any]], rid: str) -> list[str]:
    """The verifier prompts for a report, one per distinct quote, in call order."""
    from src.verify_model import Verification, verify_report

    prompts: list[str] = []

    def capture(u: str) -> tuple[Any, dict[str, int], float]:
        prompts.append(u)
        return Verification(records=[]), {}, 0.0

    verify_report(capture, records, facts(rid))
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
    for name, rids in plan.items():
        model = models[VERIFIER_KEY[name]]
        for rid in rids:
            if read_pred(name, rid) is not None:
                continue
            records = s2_records(rid, report_text(rid))
            prompts = quote_prompts(records, rid)
            jobs[(name, rid)] = (records, prompts)
            for n, u in enumerate(prompts):
                params = structured_params(model, cfg["verify"]["max_tokens"], effort, system,
                                           u, Verification)  # fmt: skip
                requests.append({"custom_id": custom_id(name, rid, f"q{n:04d}"), "params": params})
    print(f"verify: {len(jobs)} reports, {len(requests)} quotes")
    label = f"verify-{config_hash(cfg)}"
    ok, failed = run_batch(client, label, requests, cfg["batch"]["poll_seconds"],
                           cfg["batch"]["retries"])  # fmt: skip
    for (name, rid), (records, prompts) in jobs.items():
        model = models[VERIFIER_KEY[name]]
        answers: dict[str, tuple[Any, dict[str, int], float]] = {}
        usage: Counter[str] = Counter()
        missing = 0
        for n, u in enumerate(prompts):
            message = ok.get(custom_id(name, rid, f"q{n:04d}"))
            try:
                result = parsed(message, Verification) if message else None
            except (RuntimeError, ValueError):
                result = None
            if message is not None:
                usage.update(usage_dict(message.usage))
            missing += result is None
            answers[u] = (result or Verification(records=[]), {}, 0.0)
        verdicts, run = verify_report(lambda u, a=answers: a[u], records, facts(rid))
        total = {k: usage.get(k, 0) for k in usage_dict(object())}
        write_pred(pred_path(name, rid), run_payload(
            name, rid, model, effort, cfg, total, label,
            n_records=len(records), verdicts=verdicts, reasons=run["reasons"],
            quotes_without_answer=missing,
        ))  # fmt: skip
        print(f"{name} {rid}: {len(records)} records, {len(prompts)} quotes, {missing} unanswered")
    if failed:
        print(f"verify: {len(failed)} quotes failed after retries; their fields stay unjudged")


# --- stage 4: the ledger -------------------------------------------------------------


def manifest(path: Path = MANIFEST) -> dict[str, str]:
    """{report id: source url} for every collected report."""
    rows = pl.read_csv(path, infer_schema_length=0).filter(pl.col("status") == "ok")
    rids = [f"{s}-{d}" for s, d in zip(rows["source"], rows["date"], strict=True)]
    return dict(zip(rids, rows["url"].to_list(), strict=True))


def ledger_rows(
    records: list[dict[str, Any]], text: str, rid: str, url: str, system: str, run_id: str,
    unit_table: list[dict[str, str]], fuzzy_min: float,
) -> list[dict[str, Any]]:  # fmt: skip
    """Geocoded S3 records of one report as validated ledger rows (JSON-ready dicts).

    RUMOD rows point to the channel post that holds their evidence (amendment A2)."""
    from src.units import unit_ids

    source, day = split_report_id(rid)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    out = []
    fields = LedgerEvent.model_fields  # the schema forbids extra keys (geocode_how, ...)
    for i, r in enumerate(records):
        row_url = url
        if source == "rumod" and r.get("evidence_start") is not None:
            row_url = post_url_at(text, r["evidence_start"]) or url
        row = LedgerEvent.model_validate({
            **{k: v for k, v in r.items() if k in fields},
            "event_id": f"{rid}:{system}:{i}", "report_id": rid, "source": source,
            "section": "FULL", "sector": "FULL", "report_date": day,
            "unit_ids": unit_ids(r.get("units") or [], unit_table, fuzzy_min),
            "text_sha256": sha, "source_url": row_url, "system": system, "run_id": run_id,
        })  # fmt: skip
        out.append(row.model_dump(mode="json"))
    return out


def build(cfg: dict[str, Any], rids: list[str], out: Path = LEDGER) -> pl.DataFrame:
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
    for rid in rids:
        source, day = split_report_id(rid)
        text = report_text(rid)
        kept, _ = verified(system, rid, text)
        located = geocode_s3(kept, text, day, gaz, cfg["geocode"], chooser, source)
        rows += ledger_rows(located, text, rid, urls[rid], system, run_id, units,
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
    ap.add_argument("--sources", default=",".join(load_config()["ledger"]["sources"]),
                    help="comma-separated; default config ledger.sources")  # fmt: skip
    args = ap.parse_args(argv)
    cfg = load_config()
    sources = args.sources.split(",")
    unready = [s for s in sources if s in A2_SOURCES and not a2_key_ready(s, cfg)]
    if unready:
        raise SystemExit(f"no frozen test key for {', '.join(unready)} yet; make it first with "
                         "src.review_a2 --split test (amendment A2)")  # fmt: skip
    rids = corpus_reports(cfg, sources)
    test_rids = test_reports(cfg, sources)
    if args.stage == "run":
        from src.verify_model import geocode_choices

        load_dotenv(ROOT / ".env")
        client = anthropic.Anthropic()
        extract_stage(client, cfg, rids, test_rids)
        shipped = cfg["ledger"]["system"]
        plan = {shipped: rids}
        plan.update({s: test_rids for s in cfg["ledger"]["test_only_systems"] if s in VERIFIER_KEY})
        verify_stage(client, cfg, plan)
        for name, which in plan.items():
            for source in sources:
                days = [split_report_id(r)[1] for r in which if r.startswith(f"{source}-")]
                geocode_choices(client, cfg, name, days, source)
    all_sources = ",".join(cfg["ledger"]["sources"])
    built = [s for s in all_sources.split(",") if s not in A2_SOURCES or a2_key_ready(s, cfg)]
    frame = build(cfg, corpus_reports(cfg, built))
    print(summary(frame))
    print(f"wrote {LEDGER.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
