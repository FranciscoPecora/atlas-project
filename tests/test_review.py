from types import SimpleNamespace

import pytest

from src.labels import SPEC
from src.prelabel import prefill_report
from src.review import (
    METHOD,
    RefusedTestSplit,
    Review,
    ReviewedEvent,
    build_prompt,
    dev_task_data,
    guideline_rules,
    has_quantity,
    is_human_labelled,
    review_report,
    to_records,
    write_gold,
)

TEXT = (
    "Заголовок звіту\n\n"
    "На Лиманському напрямку ворог атакував 5 разів у районі Ясного. "
    "Противник завдав трьох авіаційних ударів.\n\n"
    "Слава Україні."
)
DATA = {
    "report_id": "gsu-2026-07-21",
    "source": "gsu",
    "report_date": "2026-07-21",
    "sector": "FULL",
    "text_sha256": "abc",
    "source_url": "https://example.org/r",
}
MODELS = {"gold_review": "model-from-config", "gold_review_effort": "high"}


def event(**changes) -> ReviewedEvent:
    base = {
        "paragraph": 2,
        "event_type": "ground_assault",
        "epistemic_status": "ua_claimed",
        "actor": "RU",
        "target": "UA",
        "location_text": "Ясного",
        "geo_precision": 2,
        "quantity": 5,
        "evidence_quote": "На Лиманському напрямку ворог атакував 5 разів у районі Ясного.",
    }
    return ReviewedEvent(**{**base, **changes})


def test_guideline_rules_drop_procedure_and_log():
    g = "# G\n\n## 1. What\nrule\n\n## 8. Procedure\nclick\n\n## 9. Hard\nruling\n\n## 10. Log\nx"
    out = guideline_rules(g)
    assert "rule" in out and "ruling" in out
    assert "click" not in out and "Log" not in out


def test_build_prompt_lists_drafts_under_their_paragraph():
    prompt = build_prompt(TEXT, prefill_report(TEXT))
    assert "[1] Заголовок звіту\n  draft: (nothing)" in prompt
    assert "draft: ground_assault | place: Ясного | quantity: 5" in prompt


def test_has_quantity_accepts_digits_and_number_words():
    assert has_quantity("атакував 5 разів", 5)
    assert has_quantity("завдав трьох авіаційних ударів", 3)
    assert not has_quantity("атакував 5 разів", 6)


def test_to_records_computes_offsets_and_sets_date_and_source():
    records, rejected = to_records(Review(events=[event()]), TEXT, DATA)
    assert rejected == []
    r = records[0]
    assert TEXT[r["evidence_start"] : r["evidence_end"]] == event().evidence_quote
    assert r["event_date"] == "2026-07-20"
    assert r["claim_source"] == "Ukrainian General Staff"
    assert "evidence_quote" not in r


def test_to_records_rejects_what_is_not_in_the_text():
    bad = [
        event(evidence_quote="Ворог атакував біля Ясного."),
        event(location_text="Ясне"),
        event(quantity=7),
        event(paragraph=9),
    ]
    records, rejected = to_records(Review(events=bad), TEXT, DATA)
    assert records == []
    assert len(rejected) == 4


def test_review_report_takes_model_and_effort_from_config():
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=Review(events=[event()]))

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    guideline = "## 1. A\nrule\n## 8. P\n\n## 9. H\n\n## 10. L"
    assert review_report(client, MODELS, TEXT, guideline).events[0].quantity == 5
    assert seen["model"] == "model-from-config"
    assert seen["output_config"] == {"effort": "high"}
    assert "rule" in seen["system"]


def test_test_split_and_unknown_dates_are_refused():
    spec = SPEC.read_text(encoding="utf-8")
    with pytest.raises(RefusedTestSplit):
        dev_task_data("2026-11-10", spec)
    with pytest.raises(ValueError):
        dev_task_data("2026-07-22", spec)


def test_write_gold_marks_method_and_protects_hand_labels(tmp_path):
    records, _ = to_records(Review(events=[event()]), TEXT, DATA)
    path = tmp_path / "dev" / "gsu-2026-07-21__FULL__pass1.jsonl"
    write_gold(path, records, "model-from-config")
    assert f'"label_method": "{METHOD}"' in path.read_text(encoding="utf-8")
    assert not is_human_labelled(path)
    path.write_text('{"event_type": "shelling"}\n', encoding="utf-8")
    assert is_human_labelled(path)
