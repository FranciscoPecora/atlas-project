from types import SimpleNamespace

import pytest

from src.verify_model import (
    FieldVerdict,
    Judged,
    RecordVerdict,
    Verification,
    apply,
    apply_all,
    group_by_quote,
    judged_fields,
    user_prompt,
    verdict_map,
    verify_quote,
    verify_report,
)

# Invented records, never real report text.
Q1 = "The enemy attacked near Alfa and Bravo."
Q2 = "Three shellings of Charlie."


def rec(place, quote=Q1, **kw):
    base = {"event_type": "ground_assault", "epistemic_status": "ua_claimed",
            "claim_source": "General Staff", "actor": "RU", "actor_text": None, "target": "UA",
            "target_text": None, "location_text": place, "geo_precision": 2,
            "event_date": "2026-07-20", "units": [], "equipment": [], "quantity": None,
            "evidence_quote": quote}  # fmt: skip
    return {**base, **kw}


FACTS = {"source": "gsu", "report_date": "2026-07-21", "default_date": "2026-07-20"}


def verdict(n, **fields):
    return RecordVerdict(
        record=n, fields=[FieldVerdict(field=Judged(f), supported=s) for f, s in fields.items()]
    )


def test_judged_fields_skip_empty_values_and_the_quote():
    got = judged_fields(rec("Alfa"))
    assert "evidence_quote" not in got and "quantity" not in got and "units" not in got
    assert got["location_text"] == "Alfa"


def test_prompt_shows_one_quote_the_facts_and_numbered_records():
    text = user_prompt(Q1, [rec("Alfa"), rec("Bravo")], FACTS)
    assert text.count(Q1) == 1
    assert "Default event date (when the quote gives none): 2026-07-20" in text
    assert 'Record 1: {"event_type"' in text and '"location_text": "Bravo"' in text


def test_records_are_grouped_by_their_quote():
    records = [rec("Alfa"), rec("Charlie", Q2), rec("Bravo")]
    assert group_by_quote(records) == {Q1: [0, 2], Q2: [1]}


def test_verdict_numbers_outside_the_input_are_ignored():
    result = Verification(records=[verdict(1, actor=True), verdict(7, actor=False)])
    assert verdict_map(result, 2) == {0: {"actor": True}}


def test_unsupported_optional_field_is_set_to_null():
    r = rec("Alfa", quantity=3, equipment=["tank"])
    out, removed, unjudged = apply(r, {**dict.fromkeys(judged_fields(r), True),
                                       "quantity": False, "equipment": False})  # fmt: skip
    assert out["quantity"] is None and out["equipment"] == []
    assert sorted(removed) == ["equipment", "quantity"] and unjudged == []


@pytest.mark.parametrize("field", ["event_type", "location_text", "epistemic_status", "event_date"])
def test_unsupported_core_field_drops_the_record(field):
    r = rec("Alfa")
    out, removed, _ = apply(r, {**dict.fromkeys(judged_fields(r), True), field: False})
    assert out is None and removed == [field]


def test_a_field_the_model_skipped_is_kept_and_reported():
    r = rec("Alfa")
    out, removed, unjudged = apply(r, {"event_type": True})
    assert out == r and removed == [] and "location_text" in unjudged


def test_verify_report_makes_one_call_per_quote_and_maps_verdicts_back():
    records = [rec("Alfa"), rec("Charlie", Q2), rec("Bravo")]
    prompts = []

    def call(user):
        prompts.append(user)
        if Q2 in user:
            return Verification(records=[verdict(1, location_text=False)]), {"input_tokens": 5}, 1.0
        return (
            Verification(records=[verdict(1, actor=True), verdict(2, quantity=True)]),
            {"input_tokens": 7},
            2.0,
        )

    verdicts, run = verify_report(call, records, FACTS)
    assert len(prompts) == 2
    assert verdicts == [{"actor": True}, {"location_text": False}, {"quantity": True}]
    assert run["usage"] == {"input_tokens": 12} and run["seconds"] == 3.0
    assert run["reasons"] == [{"record": 1, "field": "location_text", "reason": None}]


def test_apply_all_counts_removals_drops_and_unjudged():
    records = [rec("Alfa"), rec("Bravo")]
    ok = dict.fromkeys(judged_fields(records[0]), True)
    kept, counts = apply_all(records, [{**ok, "actor": False}, None])
    assert len(kept) == 2 and kept[0]["actor"] is None
    assert counts["removed"] == {"actor": 1} and counts["dropped"] == {}
    assert counts["unjudged"]["event_type"] == 1  # the record whose call gave nothing
    kept, counts = apply_all(records, [{**ok, "location_text": False}, ok])
    assert len(kept) == 1 and counts["dropped"] == {"location_text": 1}


def test_verify_quote_sends_the_config_model_and_rejects_a_bad_stop():
    seen = {}

    def parse(**kw):
        seen.update(kw)
        return SimpleNamespace(
            stop_reason="end_turn",
            parsed_output=Verification(records=[]),
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    cfg = {"models": {"verifier": "m-h", "verifier_effort": "low"},
           "verify": {"max_tokens": 100, "timeout_seconds": 5}}  # fmt: skip
    result, usage, _ = verify_quote(client, cfg, "verifier", "sys", "user")
    assert seen["model"] == "m-h" and seen["output_format"] is Verification
    assert usage["input_tokens"] == 10 and result.records == []

    def refused(**kw):
        return SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=None)

    client.beta.messages.parse = refused
    with pytest.raises(RuntimeError):
        verify_quote(client, cfg, "verifier", "sys", "user")
