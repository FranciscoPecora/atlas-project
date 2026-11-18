from types import SimpleNamespace

import pytest

from src.extract import (
    cost_usd,
    example_events,
    examples_block,
    extract_section,
    instructions,
    pred_path,
    read_pred,
    to_records,
    usage_dict,
    user_prompt,
    write_pred,
)
from src.schema import ExtractionResult

# Invented sentences, never real report text.
TEXT = "Title line\n\nThe enemy attacked near Alfa and Bravo.\n\nNo attacks were recorded."
QUOTE = "The enemy attacked near Alfa and Bravo."
GOLD = [
    {"event_type": "ground_assault", "epistemic_status": "ua_claimed", "claim_source": "GS",
     "actor": "RU", "target": "UA", "location_text": place, "geo_precision": 2,
     "event_date": "2026-07-20", "quantity": None,
     "evidence_start": TEXT.index(QUOTE), "evidence_end": TEXT.index(QUOTE) + len(QUOTE)}
    for place in ("Alfa", "Bravo")
]  # fmt: skip
DATA = {"report_id": "gsu-2026-07-21", "source": "gsu", "report_date": "2026-07-21",
        "sector": "FULL"}  # fmt: skip
CFG = {
    "models": {"extraction": "test-model"},
    "extract": {"max_tokens": 100, "timeout_seconds": 5},
}


def test_instructions_keep_the_rules_and_drop_the_procedure():
    guideline = (
        "# G\n\n## 1. Rules\nrule one\n\n## 8. Procedure\nsteps\n\n## 9. Hard\nh\n\n## 10. Log\nx"
    )
    out = instructions(guideline)
    assert "rule one" in out and "## 9." in out
    assert "steps" not in out and "Log" not in out


def test_user_prompt_puts_the_text_last():
    out = user_prompt("2026-07-21", "2026-07-20", "FULL", "BODY")
    assert out.endswith("BODY") and "2026-07-20" in out


def test_example_events_take_the_quote_from_the_text():
    a = TEXT.index(QUOTE)
    events = example_events(GOLD, TEXT, a, a + len(QUOTE))
    assert [e["location_text"] for e in events] == ["Alfa", "Bravo"]
    assert all(e["evidence_quote"] == QUOTE for e in events)
    assert "evidence_start" not in events[0]  # the model never sees or returns offsets


def test_examples_block_includes_a_zero_event_example():
    out = examples_block(TEXT, GOLD, [2, 3], "2026-07-21", "2026-07-20")
    assert "## Example 2" in out and out.endswith('{"events": []}')
    ExtractionResult.model_validate_json(out.split("Output:\n")[1].split("\n\n")[0])


def test_usage_and_cost():
    usage = usage_dict(SimpleNamespace(input_tokens=1_000_000, output_tokens=2_000_000,
                                       cache_read_input_tokens=None))  # fmt: skip
    assert usage["cache_read_input_tokens"] == 0 and usage["cache_creation_input_tokens"] == 0
    price = {"input": 0.1, "output": 0.5, "cache_write": 0.125, "cache_read": 0.01}
    assert cost_usd(usage, price) == pytest.approx(1.1)


def fake_client(parsed, stop="end_turn"):
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        usage = SimpleNamespace(input_tokens=5, output_tokens=7)
        return SimpleNamespace(parsed_output=parsed, stop_reason=stop, usage=usage)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    return client, seen


def test_extract_section_sends_config_values_and_the_schema():
    client, seen = fake_client(ExtractionResult(events=[]))
    result, usage, seconds = extract_section(client, CFG, "SYS", "USER", "low")
    assert result.events == [] and usage["output_tokens"] == 7 and seconds >= 0
    assert seen["model"] == "test-model" and seen["output_config"] == {"effort": "low"}
    assert seen["output_format"] is ExtractionResult
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["messages"][0]["content"] == "USER"


def test_extract_section_raises_when_cut_off():
    client, _ = fake_client(None, stop="max_tokens")
    with pytest.raises(RuntimeError):
        extract_section(client, CFG, "SYS", "USER", "low")


def test_to_records_never_rejects_and_adds_offsets_when_found():
    events = [{"evidence_quote": QUOTE, "location_text": "Alfa"},
              {"evidence_quote": "not in the text", "location_text": None}]  # fmt: skip
    records = to_records(events, TEXT, DATA, "S1")
    assert len(records) == 2
    assert TEXT[records[0]["evidence_start"] : records[0]["evidence_end"]] == QUOTE
    assert records[1]["evidence_start"] is None
    assert records[0]["id"] == "gsu-2026-07-21:S1:0" and records[0]["sector"] == "FULL"


def test_pred_round_trip(tmp_path):
    write_pred(pred_path("S1", "gsu-x", tmp_path), {"events": [1]})
    assert read_pred("S1", "gsu-x", tmp_path) == {"events": [1]}
    assert read_pred("S1", "gsu-y", tmp_path) is None
