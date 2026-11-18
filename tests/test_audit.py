import json

import pytest

from src.audit import (
    build_items,
    clean_answers,
    committable,
    draw,
    english_paragraphs,
    glossary,
    paragraph_of,
    render_page,
    score,
    wilson,
)
from src.prelabel import paragraph_spans

TEXT = "Заголовок звіту\n\nВорог атакував 5 разів у районі Ясного.\n\nСлава Україні."
AID = {
    "translation": "[1] starts: Заголовок звіту\nReport title\n\n"
    "[2] starts: Ворог атакував 5 разів …\nThe enemy attacked 5 times near Yasne.\n\n"
    "[3] starts: Слава Україні.\nGlory to Ukraine.",
    "places": "Ясного = Yasne",
}
START = TEXT.index("Ворог")
RECORD = {
    "report_id": "gsu-2026-07-21",
    "report_date": "2026-07-21",
    "event_type": "ground_assault",
    "epistemic_status": "ua_claimed",
    "actor": "RU",
    "target": "UA",
    "location_text": "Ясного",
    "quantity": 5,
    "event_date": "2026-07-20",
    "evidence_start": START,
    "evidence_end": START + len("Ворог атакував 5 разів у районі Ясного."),
    "label_method": "rules+review-v1",
}


def test_reading_aid_is_split_by_paragraph_number():
    en = english_paragraphs(AID["translation"])
    assert en == {
        1: "Report title",
        2: "The enemy attacked 5 times near Yasne.",
        3: "Glory to Ukraine.",
    }
    assert glossary(AID["places"]) == {"Ясного": "Yasne"}


def test_paragraph_of_finds_the_containing_paragraph():
    assert paragraph_of(paragraph_spans(TEXT), START) == 2


def test_draw_is_seeded_and_bounded():
    records = [{**RECORD, "evidence_start": i} for i in range(50)]
    a = draw(records, {"gsu-2026-07-21": 20}, 30, 10, seed=7)
    assert a == draw(records, {"gsu-2026-07-21": 20}, 30, 10, seed=7)
    assert [s["kind"] for s in a].count("event") == 30
    assert [s["kind"] for s in a].count("paragraph") == 10
    assert len({s["id"] for s in a}) == 40
    assert len(draw(records[:3], {"gsu-2026-07-21": 2}, 30, 10, seed=7)) == 5


def test_items_show_english_place_and_all_events_of_a_paragraph():
    sample = draw([RECORD], {"gsu-2026-07-21": 3}, 1, 3, seed=1)
    items = build_items(sample, [RECORD], {"gsu-2026-07-21": TEXT}, {"gsu-2026-07-21": AID})
    event = items[0]
    assert event["paragraph"] == 2 and "Yasne" in event["english"]
    assert event["events"][0]["place_en"] == "Yasne"
    assert event["events"][0]["same_kind"] == 1
    assert event["events"][0]["quote"].startswith("Ворог атакував")
    by_paragraph = {i["paragraph"]: i for i in items if i["kind"] == "paragraph"}
    assert len(by_paragraph[2]["events"]) == 1 and by_paragraph[3]["events"] == []


def test_committed_sample_has_offsets_but_no_text():
    sample = draw([RECORD], {"gsu-2026-07-21": 3}, 1, 0, seed=1)
    row = committable(sample[0], [RECORD])
    assert row["evidence_start"] == START and "record" not in row
    assert "Ясного" not in json.dumps(row, ensure_ascii=False)


def test_render_page_embeds_items_safely():
    page = render_page([{"id": "e01", "english": "</script>"}], "<script>/*ITEMS*/[]</script>")
    assert '"id": "e01"' in page and '</script>"' not in page


def test_wilson_interval():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(1, 30)
    assert lo == pytest.approx(0.006, abs=0.001) and hi == pytest.approx(0.167, abs=0.001)


def test_score_counts_errors_misses_and_gaps():
    sample = [
        {"id": "e01", "kind": "event"},
        {"id": "e02", "kind": "event"},
        {"id": "e03", "kind": "event"},
        {"id": "p01", "kind": "paragraph"},
        {"id": "p02", "kind": "paragraph"},
    ]
    answers = {
        "e01": {"verdict": "right"},
        "e02": {"verdict": "wrong"},
        "e03": {"verdict": "unsure"},
        "p01": {"verdict": "complete"},
    }
    res = score(sample, answers)
    assert res["event"]["rate"] == 0.5 and res["event"]["unsure"] == 1
    assert res["paragraph"]["rate"] == 0.0 and res["paragraph"]["unanswered"] == 1


def test_clean_answers_keeps_verdict_and_note_only():
    raw = {"answers": {"e01": {"verdict": "wrong", "note": "bad place", "extra": 1}}}
    assert clean_answers(raw) == {"e01": {"verdict": "wrong", "note": "bad place"}}
    with pytest.raises(ValueError):
        clean_answers({"answers": {"e01": {"verdict": "maybe"}}})


def test_test_split_answers_are_committed_without_notes(tmp_path, monkeypatch):
    import src.audit as audit

    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path / "eval")
    monkeypatch.setattr(audit, "PAGE", tmp_path / "data" / "audit.html")
    (tmp_path / "eval").mkdir()
    (tmp_path / "data").mkdir()
    sample = [{"id": "e01", "kind": "event"}, {"id": "p01", "kind": "paragraph"}]
    (tmp_path / "eval" / "test_sample_round1.json").write_text(json.dumps(sample), "utf-8")
    raw = {"answers": {"e01": {"verdict": "wrong", "note": "quoted words"}}}
    (tmp_path / "a.json").write_text(json.dumps(raw), "utf-8")
    cfg = {"audit": {"round": 2, "test_round": 1, "max_error_rate": 0.05}}
    audit.report(cfg, tmp_path / "a.json", "test")
    committed = (tmp_path / "eval" / "test_answers_round1.json").read_text("utf-8")
    assert "quoted words" not in committed and '"wrong"' in committed
    assert "quoted words" in (tmp_path / "data" / "test_notes_round1.json").read_text("utf-8")
