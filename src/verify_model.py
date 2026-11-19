"""Model field verification (pipeline step 4, systems S3-H and S3-S; SPEC.md section 6).

    uv run python -m src.verify_model --set dev              # models.verifier
    uv run python -m src.verify_model --set dev --alt        # models.verifier_alt
    uv run python -m src.verify_model --set audit [--alt]    # the audit reports

A separate call sees one evidence quote and the records that cite it, never the
section. It answers, per non-empty field, whether the quote supports it. The call
also gets three report facts that no quote states: the source, the report date
and the default event date (SPEC section 1); without them every default date and
every source-based status would be judged unsupported.

Code, not the model, applies the verdicts (`apply`): an unsupported optional
field is set to null (a list to []); an unsupported event_type, location_text,
epistemic_status or event_date drops the record, because the first two define
the event and the last two cannot be null. Verdicts are saved per run to
data/pred/<system>/ (git-ignored: they hold quotes) so scoring needs no API.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from enum import StrEnum
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.collect import DATA, ROOT
from src.config import config_hash, load_config
from src.extract import PRED, cost_usd, default_date, read_pred, usage_dict, write_pred
from src.review import GUIDELINE, guideline_rules, with_retries
from src.verify_det import verify


class Judged(StrEnum):
    event_type = "event_type"
    epistemic_status = "epistemic_status"
    claim_source = "claim_source"
    actor = "actor"
    actor_text = "actor_text"
    target = "target"
    target_text = "target_text"
    location_text = "location_text"
    geo_precision = "geo_precision"
    event_date = "event_date"
    units = "units"
    equipment = "equipment"
    quantity = "quantity"


JUDGED = tuple(f.value for f in Judged)
DROP_IF_UNSUPPORTED = ("event_type", "location_text", "epistemic_status", "event_date")
SOURCES = {
    "gsu": "Ukrainian General Staff, 08:00 operational update (the whole report is its claim)",
    "isw": "Institute for the Study of War, Russian Offensive Campaign Assessment",
    "af": "Ukrainian Air Force, report on the overnight air attack (the whole report is its "
    "claim)",
    "rumod": "Russian Ministry of Defence, Telegram channel posts of one day (every post is "
    "its claim)",
}

TASK = (
    "You check records that another model extracted from a military report. You see "
    "ONE evidence quote and the records that cite it, never the rest of the report.\n\n"
    "For every field listed under a record, answer supported = true only if the quote, "
    "read together with the report facts given, states that value. Do not use outside "
    "knowledge, and do not assume the rest of the report says it.\n"
    "- event_type and geo_precision follow the annotation guideline below.\n"
    "- event_date is supported if the quote gives that date, or if the quote gives no "
    "date and the value equals the default event date.\n"
    "- epistemic_status and claim_source may rest on the report source when the quote "
    "itself names no other source.\n"
    "- location_text must be the place the event happened at, as the quote writes it.\n"
    "- quantity must count this one event, not a total shared with other places.\n"
    "- actor and target are the sides (RU, UA, other). The report's author is one side: "
    "in its words 'the enemy' or 'the occupiers' is the other side, and 'our units' or "
    "'the defenders' is the author's side. The guideline's rules on actor and target for "
    "this kind of report apply.\n"
    "Answer for exactly the fields listed under each record, no others. Give a reason "
    "only when a field is not supported, in under 20 words."
)


class FieldVerdict(BaseModel):
    field: Judged
    supported: bool
    reason: str | None = Field(None, description="Why not, when supported is false")


class RecordVerdict(BaseModel):
    record: int = Field(description="The record number given in the input")
    fields: list[FieldVerdict]


class Verification(BaseModel):
    records: list[RecordVerdict]


def instructions(guideline: str) -> str:
    return TASK + "\n\n# Annotation guideline\n\n" + guideline_rules(guideline)


def judged_fields(record: dict[str, Any]) -> dict[str, Any]:
    """The fields the verifier is asked about: every judged field that is not empty."""
    return {f: record[f] for f in JUDGED if record.get(f) not in (None, [], "")}


def user_prompt(quote: str, records: list[dict[str, Any]], facts: dict[str, str]) -> str:
    """Report facts, the quote, then the records numbered from 1 (the quote is not repeated)."""
    lines = [
        f"Report source: {SOURCES[facts['source']]}",
        f"Report date: {facts['report_date']}",
        f"Default event date (when the quote gives none): {facts['default_date']}",
        "",
        f"Evidence quote:\n{quote}",
        "",
    ]
    for n, r in enumerate(records, 1):
        lines.append(f"Record {n}: {json.dumps(judged_fields(r), ensure_ascii=False)}")
    return "\n".join(lines)


def group_by_quote(records: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Positions of the records that share each quote, in first-seen order."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        groups[r["evidence_quote"]].append(i)
    return dict(groups)


def verdict_map(result: Verification, n_records: int) -> dict[int, dict[str, bool]]:
    """{record position (0-based): {field: supported}}; numbers outside the input are ignored."""
    out: dict[int, dict[str, bool]] = {}
    for rv in result.records:
        if 1 <= rv.record <= n_records:
            out[rv.record - 1] = {fv.field.value: fv.supported for fv in rv.fields}
    return out


def apply(
    record: dict[str, Any], verdicts: dict[str, bool]
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """(record after verification or None if dropped, fields removed, fields left unjudged).

    A field the model did not answer for is kept and reported as unjudged.
    """
    asked = judged_fields(record)
    unjudged = [f for f in asked if f not in verdicts]
    removed = [f for f in asked if verdicts.get(f) is False]
    if any(f in DROP_IF_UNSUPPORTED for f in removed):
        return None, removed, unjudged
    kept = dict(record)
    for f in removed:
        kept[f] = [] if isinstance(record[f], list) else None
    return kept, removed, unjudged


def verify_quote(
    client: Any, cfg: dict[str, Any], model_key: str, system: str, user: str
) -> tuple[Verification, dict[str, int], float]:
    """One structured verifier call. Returns verdicts, token usage and seconds."""
    models = cfg["models"]
    started = time.monotonic()
    response = client.beta.messages.parse(
        model=models[model_key],
        max_tokens=cfg["verify"]["max_tokens"],
        timeout=cfg["verify"]["timeout_seconds"],
        output_config={"effort": models["verifier_effort"]},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=Verification,
    )
    seconds = time.monotonic() - started
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"verification stopped: {response.stop_reason}")
    return response.parsed_output, usage_dict(response.usage), seconds


def verify_report(
    call: Any, records: list[dict[str, Any]], facts: dict[str, str]
) -> tuple[list[dict[str, bool] | None], dict[str, Any]]:
    """Verdicts for each record (None when its quote's call gave none), and run totals.

    `call(user_prompt) -> (Verification, usage, seconds)`.
    """
    verdicts: list[dict[str, bool] | None] = [None] * len(records)
    usage: Counter[str] = Counter()
    seconds = 0.0
    reasons: list[dict[str, Any]] = []
    for quote, positions in group_by_quote(records).items():
        group = [records[i] for i in positions]
        result, used, took = call(user_prompt(quote, group, facts))
        usage.update(used)
        seconds += took
        found = verdict_map(result, len(group))
        for j, i in enumerate(positions):
            verdicts[i] = found.get(j)
        reasons += [
            {"record": positions[rv.record - 1], "field": fv.field.value, "reason": fv.reason}
            for rv in result.records if 1 <= rv.record <= len(group)
            for fv in rv.fields if not fv.supported
        ]  # fmt: skip
    return verdicts, {"usage": dict(usage), "seconds": seconds, "reasons": reasons}


def apply_all(
    records: list[dict[str, Any]], verdicts: list[dict[str, bool] | None]
) -> tuple[list[dict[str, Any]], dict[str, Counter[str]]]:
    """Records kept after verification, and counts: removed fields, drop reasons, unjudged."""
    kept: list[dict[str, Any]] = []
    counts: dict[str, Counter[str]] = {"removed": Counter(), "dropped": Counter(),
                                       "unjudged": Counter()}  # fmt: skip
    for r, v in zip(records, verdicts, strict=True):
        out, removed, unjudged = apply(r, v or {})
        counts["removed"].update(removed)
        counts["unjudged"].update(unjudged if v is not None else list(judged_fields(r)))
        if out is None:
            counts["dropped"].update(f for f in removed if f in DROP_IF_UNSUPPORTED)
        else:
            kept.append(out)
    return kept, counts


def system_name(alt: bool) -> str:
    return "S3-S" if alt else "S3-H"


def s2_records(report_id: str, text: str) -> list[dict[str, Any]]:
    """S1's events for a report after deterministic verification (S2), with offsets."""
    run = read_pred("S1", report_id)
    if run is None:
        raise FileNotFoundError(f"no S1 extraction for {report_id}; run src.extract first")
    kept, _ = verify(run["events"], text)
    return kept


def main(argv: list[str] | None = None) -> None:
    from src.audit_fields import audit_dates
    from src.extract import dev_gsu_dates
    from src.labels import SPEC

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", choices=["dev", "audit"], default="dev")
    ap.add_argument("--alt", action="store_true", help="use models.verifier_alt")
    ap.add_argument("--force", action="store_true", help="redo reports already verified")
    ap.add_argument("--day", action="append", help="only this report date (repeatable)")
    args = ap.parse_args(argv)

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    key = "verifier_alt" if args.alt else "verifier"
    model = cfg["models"][key]
    name = system_name(args.alt)
    spec_text = SPEC.read_text(encoding="utf-8")
    days = dev_gsu_dates(spec_text) if args.set == "dev" else audit_dates(spec_text)
    days = [d for d in days if not args.day or d in args.day]
    system = instructions(GUIDELINE.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    price = cfg["prices"][model]
    for day in days:
        rid = f"gsu-{day}"
        out = PRED / name / f"{rid}.json"
        if out.exists() and not args.force:
            continue
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        records = s2_records(rid, text)
        facts = {"source": "gsu", "report_date": day,
                 "default_date": default_date({"source": "gsu", "report_date": day})}  # fmt: skip
        verdicts, run = verify_report(
            lambda u: with_retries(lambda: verify_quote(client, cfg, key, system, u)),
            records,
            facts,
        )
        usage = {k: run["usage"].get(k, 0) for k in usage_dict(object())}  # all four keys
        _, counts = apply_all(records, verdicts)
        write_pred(out, {
            "report_id": rid, "system": name, "model": model,
            "effort": cfg["models"]["verifier_effort"], "config_hash": config_hash(cfg),
            "seconds": round(run["seconds"], 2), "usage": usage,
            "cost_usd": cost_usd(usage, price), "n_records": len(records),
            "verdicts": verdicts, "reasons": run["reasons"],
        })  # fmt: skip
        print(
            f"{name} {day}: {len(records)} records, {run['seconds']:.1f} s, "
            f"${cost_usd(usage, price):.4f}, removed {dict(counts['removed'])}, "
            f"dropped {dict(counts['dropped'])}, unjudged {dict(counts['unjudged'])}"
        )
    if args.set == "dev":
        geocode_choices(client, cfg, name, days)


def geocode_choices(
    client: Any, cfg: dict[str, Any], name: str, days: list[str], source: str = "gsu"
) -> None:
    """Run the S3 geocoder on the verified records once, asking the model on weak rules.

    Choices are saved to data/pred/geocode_choices.json for scoring; the cost of new
    calls is added to each report's saved run as `geocode_cost_usd`.
    """
    from src.gazetteer import Gazetteer, read_table
    from src.geocode import cached_chooser, model_chooser
    from src.s3 import geocode_s3, load_choices, save_choices, verified

    gaz = Gazetteer(read_table())
    cache = load_choices()
    price = cfg["prices"][cfg["models"]["geocode_disambiguation"]]
    for day in days:
        rid = f"{source}-{day}"
        text = (DATA / "text" / source / f"{day}.txt").read_text(encoding="utf-8")
        kept, run = verified(name, rid, text)
        log: list[dict[str, Any]] = []
        chooser = cached_chooser(cache, model_chooser(client, cfg, log))
        geocode_s3(kept, text, day, gaz, cfg["geocode"], chooser, source)
        save_choices(cache)
        spent = sum(cost_usd(usage_dict(x["usage"]), price) for x in log)
        run.pop("counts")
        write_pred(PRED / name / f"{rid}.json", {
            **run, "geocode_calls": run.get("geocode_calls", 0) + len(log),
            "geocode_cost_usd": run.get("geocode_cost_usd", 0.0) + spent,
        })  # fmt: skip
        print(f"{name} {day}: {len(log)} geocoder model calls, ${spent:.4f}")


def read_verdicts(system: str, report_id: str, pred_dir: Path = PRED) -> dict[str, Any] | None:
    return read_pred(system, report_id, pred_dir)


if __name__ == "__main__":
    main()
