"""Baseline B2: the extraction model with one free-form prompt (SPEC.md section 6).

    uv run python -m src.baselines.b2_single_prompt     # dev General Staff reports

Same model, effort and instructions as S1, but no output schema, one worked
example instead of five, and no verification. The model is asked for a JSON
list in plain words, and the reply is parsed defensively: text around the list
is ignored, and items that are not usable events are dropped and counted.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from typing import Any

import anthropic
from dotenv import load_dotenv

from src.collect import DATA, ROOT
from src.config import config_hash, load_config
from src.extract import (
    MODEL_FIELDS,
    cost_usd,
    default_date,
    dev_gsu_dates,
    instructions,
    load_examples,
    pred_path,
    usage_dict,
    user_prompt,
    write_pred,
)
from src.labels import SPEC
from src.review import GUIDELINE, unit_task_data, with_retries

SYSTEM = "B2"
ASK = (
    "\n\nReturn only a JSON list. Each item is one event with these keys: "
    + ", ".join(MODEL_FIELDS)
    + ". Use null for a key the text does not support. Return [] if there are no events."
)


def json_list(reply: str) -> list[Any]:
    """The first JSON list found in `reply`; [] if there is none.

    Models often wrap JSON in a code fence or a sentence, or wrap the list in
    an object. Each "[" is tried in turn as the start of a list.
    """
    decoder = json.JSONDecoder()
    for at, ch in enumerate(reply):
        if ch != "[":
            continue
        try:
            value, _ = decoder.raw_decode(reply[at:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
    return []


def clean_item(item: Any, fallback_date: str) -> dict[str, Any] | None:
    """One reply item as an event dict, or None if it has no usable event type."""
    if not isinstance(item, dict) or not isinstance(item.get("event_type"), str):
        return None
    out: dict[str, Any] = {f: item.get(f) for f in MODEL_FIELDS}
    out["event_type"] = item["event_type"].strip().lower().replace(" ", "_")
    for field in ("epistemic_status", "location_text", "evidence_quote", "claim_source"):
        if out[field] is not None and not isinstance(out[field], str):
            out[field] = str(out[field])
    if isinstance(out["epistemic_status"], str):
        out["epistemic_status"] = out["epistemic_status"].strip().lower()
    try:
        out["event_date"] = date.fromisoformat(str(out["event_date"])[:10]).isoformat()
    except ValueError:
        out["event_date"] = fallback_date
    try:
        out["quantity"] = None if out["quantity"] is None else int(out["quantity"])
    except (TypeError, ValueError):
        out["quantity"] = None
    out["location_text"] = out["location_text"] or None
    return out


def parse_reply(reply: str, fallback_date: str) -> tuple[list[dict[str, Any]], int]:
    """Events parsed from a free-form reply, and the number of items dropped."""
    items = json_list(reply)
    events = [e for e in (clean_item(i, fallback_date) for i in items) if e is not None]
    return events, len(items) - len(events)


def ask(
    client: Any, cfg: dict[str, Any], system: str, user: str
) -> tuple[str, dict[str, int], float]:
    """One free-form call. Returns the reply text, token usage and wall-clock seconds."""
    started = time.monotonic()
    response = client.messages.create(
        model=cfg["models"]["extraction"],
        max_tokens=cfg["extract"]["max_tokens"],
        timeout=cfg["extract"]["timeout_seconds"],
        output_config={"effort": cfg["models"]["extraction_effort"]},
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    seconds = time.monotonic() - started
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"B2 stopped: {response.stop_reason}")
    reply = "".join(b.text for b in response.content if b.type == "text")
    return reply, usage_dict(response.usage), seconds


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    spec_text = SPEC.read_text(encoding="utf-8")
    guideline = GUIDELINE.read_text(encoding="utf-8")
    system = instructions(guideline) + "\n\n" + load_examples(cfg, limit=1) + ASK
    client = anthropic.Anthropic()
    price = cfg["prices"][cfg["models"]["extraction"]]
    for day in dev_gsu_dates(spec_text):
        data = unit_task_data(day, spec_text)  # refuses test-split reports
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        user = user_prompt(day, default_date(data), data["sector"], text)
        reply, usage, seconds = with_retries(lambda user=user: ask(client, cfg, system, user))
        events, dropped = parse_reply(reply, default_date(data))
        write_pred(
            pred_path(SYSTEM, data["report_id"]),
            {
                "report_id": data["report_id"],
                "system": SYSTEM,
                "model": cfg["models"]["extraction"],
                "effort": cfg["models"]["extraction_effort"],
                "config_hash": config_hash(cfg),
                "seconds": round(seconds, 2),
                "usage": usage,
                "cost_usd": cost_usd(usage, price),
                "dropped_items": dropped,
                "events": events,
            },
        )
        print(f"{SYSTEM} {day}: {len(events)} events ({dropped} items dropped), {seconds:.1f} s, "
              f"${cost_usd(usage, price):.5f}, tokens {usage}")  # fmt: skip


if __name__ == "__main__":
    main()
