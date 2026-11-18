from types import SimpleNamespace

import pytest

from src.baselines.b2_single_prompt import ask, clean_item, json_list, parse_reply


def test_json_list_ignores_fences_and_chatter():
    reply = 'Here you go [sic]:\n```json\n[{"event_type": "shelling"}]\n```\nDone.'
    assert json_list(reply) == [{"event_type": "shelling"}]


def test_json_list_finds_a_list_wrapped_in_an_object():
    assert json_list('{"events": [{"event_type": "other"}]}') == [{"event_type": "other"}]


def test_json_list_none_or_broken():
    assert json_list("No events found.") == []
    assert json_list('[{"event_type": "shelling"') == []


def test_clean_item_repairs_loose_values():
    item = {"event_type": " Ground Assault ", "epistemic_status": "UA_Claimed",
            "event_date": "20 July", "quantity": "three", "location_text": ""}  # fmt: skip
    out = clean_item(item, "2026-07-20")
    assert out["event_type"] == "ground_assault" and out["epistemic_status"] == "ua_claimed"
    assert out["event_date"] == "2026-07-20" and out["quantity"] is None
    assert out["location_text"] is None


def test_clean_item_keeps_good_values():
    out = clean_item({"event_type": "shelling", "event_date": "2026-07-19T00:00", "quantity": "4"},
                     "2026-07-20")  # fmt: skip
    assert out["event_date"] == "2026-07-19" and out["quantity"] == 4


def test_clean_item_drops_what_is_not_an_event():
    assert clean_item("shelling", "2026-07-20") is None
    assert clean_item({"location_text": "Alfa"}, "2026-07-20") is None


def test_parse_reply_counts_dropped_items():
    events, dropped = parse_reply('[{"event_type": "other"}, 7, {"x": 1}]', "2026-07-20")
    assert len(events) == 1 and dropped == 2


def test_ask_uses_no_schema_and_joins_text_blocks():
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        content = [SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="[]")]
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        return SimpleNamespace(content=content, stop_reason="end_turn", usage=usage)

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    cfg = {"models": {"extraction": "m", "extraction_effort": "low"},
           "extract": {"max_tokens": 10, "timeout_seconds": 5}}  # fmt: skip
    reply, usage, _ = ask(client, cfg, "SYS", "USER")
    assert reply == "[]" and usage["input_tokens"] == 1
    assert "output_format" not in seen and seen["model"] == "m"


def test_ask_raises_when_cut_off():
    def create(**kwargs):
        return SimpleNamespace(content=[], stop_reason="max_tokens", usage=SimpleNamespace())

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    cfg = {"models": {"extraction": "m", "extraction_effort": "low"},
           "extract": {"max_tokens": 10, "timeout_seconds": 5}}  # fmt: skip
    with pytest.raises(RuntimeError):
        ask(client, cfg, "SYS", "USER")
