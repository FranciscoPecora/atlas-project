from types import SimpleNamespace as NS

import polars as pl
import pytest

from src import ledger
from src.schema import ExtractionResult

CFG = {"corpus": {"start": "2026-07-19", "end": "2026-11-15"},
       "prices": {"m": {"input": 1.0, "output": 2.0, "cache_write": 1.25, "cache_read": 0.1}},
       "batch": {"price_factor": 0.5}}  # fmt: skip


def record(quote: str, place: str | None, start: int = 0, **extra) -> dict:
    return {
        "event_type": "ground_assault", "epistemic_status": "ua_claimed", "actor": "RU",
        "location_text": place, "geo_precision": 1 if place else None,
        "event_date": "2026-08-01", "evidence_quote": quote, "units": [], "equipment": [],
        "evidence_start": start, "evidence_end": start + len(quote),
        "lat": 48.0 if place else None, "lon": 37.0 if place else None,
        "gazetteer_id": "gn:1" if place else None, **extra,
    }  # fmt: skip


def test_corpus_days_keeps_the_window(tmp_path):
    folder = tmp_path / "text" / "gsu"
    folder.mkdir(parents=True)
    for d in ("2026-07-18", "2026-07-19", "2026-11-15", "2026-11-16"):
        (folder / f"{d}.txt").write_text("x")
    assert ledger.corpus_days(CFG, tmp_path) == ["2026-07-19", "2026-11-15"]


def test_structured_params_carry_schema_and_effort():
    p = ledger.structured_params("m", 100, "low", "SYS", "USER", ExtractionResult)
    assert p["output_config"]["effort"] == "low"
    assert p["output_config"]["format"]["type"] == "json_schema"
    assert "events" in p["output_config"]["format"]["schema"]["properties"]
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "fallbacks" not in p  # the Batches API refuses it


def test_structured_params_without_schema_is_free_form():
    p = ledger.structured_params("m", 100, "low", "SYS", "USER", None)
    assert p["output_config"] == {"effort": "low"}


def test_parsed_validates_and_refuses_unfinished_replies():
    ok = NS(stop_reason="end_turn", content=[NS(type="text", text='{"events": []}')])
    assert ledger.parsed(ok, ExtractionResult).events == []
    cut = NS(stop_reason="max_tokens", content=[NS(type="text", text='{"ev')])
    with pytest.raises(RuntimeError):
        ledger.parsed(cut, ExtractionResult)


def test_run_payload_prices_at_the_batch_rate():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 0}  # fmt: skip
    out = ledger.run_payload("S1", "gsu-x", "m", "low", CFG, usage, "extract-abc", events=[])
    assert out["cost_usd"] == pytest.approx(0.5)
    assert out["seconds"] is None and out["batch"] == "extract-abc" and out["events"] == []


def test_quote_prompts_one_per_distinct_quote():
    recs = [record("A near X and Y", "X"), record("A near X and Y", "Y"), record("B at Z", "Z")]
    prompts = ledger.quote_prompts(recs, "2026-08-02")
    assert len(prompts) == 2
    assert "A near X and Y" in prompts[0] and "Record 2" in prompts[0]
    assert "2026-08-01" in prompts[1]  # default event date = report date minus one day


def test_ledger_rows_validate_and_drop_extra_keys():
    text = "B at Z"
    recs = [record(text, "Z", geocode_how="exact", direction=None, id="tmp", system="S3-H")]
    rows = ledger.ledger_rows(recs, text, "2026-08-02", "https://u", "S3-H", "run1", [], 85)
    (row,) = rows
    assert row["event_id"] == "gsu-2026-08-02:S3-H:0"
    assert row["report_date"] == "2026-08-02" and row["source_url"] == "https://u"
    assert len(row["text_sha256"]) == 64 and row["unit_ids"] == []
    assert "geocode_how" not in row and "direction" not in row


def test_summary_counts_located_events():
    frame = pl.DataFrame([
        {"report_id": "a", "lat": 1.0, "event_type": "shelling", "epistemic_status": "ua_claimed"},
        {"report_id": "a", "lat": None, "event_type": "shelling",
         "epistemic_status": "ua_claimed"},
    ])  # fmt: skip
    assert "2 events in 1 reports; 1 located (50.0%)" in ledger.summary(frame)
