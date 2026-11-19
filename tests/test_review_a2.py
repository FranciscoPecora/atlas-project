import json

from src import review_a2
from src.review import Review

AF_TEXT = (
    "Знешкоджені 163 зі 181 БПЛА\n\n"
    "У ніч на 3 серпня противник атакував 181 ударним БПЛА.\n\n"
    "ППО збила 163 ворожі БПЛА."
)
RU_TEXT = (
    "Russian Ministry of Defence, Telegram channel, 2026-07-04 (Moscow time)\n\n"
    "## https://t.me/mod_russia/7 · 13:57\n"
    "Подразделения освободили населенный пункт Василевка в ДНР.\n\n"
    "## https://t.me/mod_russia/9 · 18:25\n"
    "ПВО перехвачены 92 беспилотника."
)


def data(source: str, day: str = "2026-08-03") -> dict:
    return {"report_id": f"{source}-{day}", "source": source, "report_date": day,
            "sector": "FULL", "split": "dev", "text_sha256": "c" * 64,
            "source_url": "https://u/first"}  # fmt: skip


def ev(paragraph, quote, etype="drone_strike", place=None, qty=None, actor="RU", target="UA"):
    return {"paragraph": paragraph, "event_type": etype, "epistemic_status": "ua_claimed",
            "actor": actor, "target": target, "location_text": place,
            "geo_precision": 1 if place else None, "quantity": qty,
            "evidence_quote": quote}  # fmt: skip


def test_guideline_for_a2_keeps_rules_8_4_and_hard_cases():
    text = "# G\n\n## 1. A\nrule\n\n## 8. Procedure\nx\n\n### 8.4 Air Force\nnew rule\n\n## 9. Hard cases\n| 14 |\n\n## 10. Pilot log\nlog"  # noqa: E501
    out = review_a2.guideline_rules_a2(text)
    assert "rule" in out and "### 8.4 Air Force\nnew rule" in out and "| 14 |" in out
    assert "Procedure" not in out and "Pilot log" not in out


def test_real_guideline_has_section_8_4():
    out = review_a2.guideline_rules_a2(review_a2.GUIDELINE.read_text(encoding="utf-8"))
    assert "Russian MoD (RUMOD)" in out and "## 9." in out


def test_af_records_get_offsets_claim_source_and_report_date():
    review = Review.model_validate({"events": [
        ev(2, "противник атакував 181 ударним БПЛА", qty=181),
        ev(3, "ППО збила 163 ворожі БПЛА", "air_defence_interception", qty=163,
           actor="UA", target="RU"),
        ev(3, "ППО збила 999", qty=999),
        ev(2, "не з тексту"),
    ]})  # fmt: skip
    records, rejected = review_a2.to_records(review, AF_TEXT, data("af"))
    assert len(records) == 2 and len(rejected) == 2
    r = records[0]
    assert AF_TEXT[r["evidence_start"] : r["evidence_end"]] == "противник атакував 181 ударним БПЛА"
    assert r["claim_source"] == "Ukrainian Air Force" and r["event_date"] == "2026-08-03"
    assert r["quantity"] == 181 and "evidence_quote" not in r
    assert any("quote is not in" in x for x in rejected)


def test_rumod_records_point_to_their_post_and_refuse_url_lines():
    review = Review.model_validate({"events": [
        ev(2, "освободили населенный пункт Василевка", "territorial_advance", "Василевка"),
        ev(3, "перехвачены 92 беспилотника", "air_defence_interception", qty=92,
           actor="RU", target="UA"),
        ev(2, "## https://t.me/mod_russia/7"),
    ]})  # fmt: skip
    records, rejected = review_a2.to_records(review, RU_TEXT, data("rumod", "2026-07-04"))
    assert [r["source_url"] for r in records] == [
        "https://t.me/mod_russia/7", "https://t.me/mod_russia/9"]  # fmt: skip
    assert records[0]["claim_source"] == "Russian Ministry of Defence"
    assert rejected == ["[2] drone_strike -: quote holds a post-URL line"]


def test_save_marks_the_a2_method(tmp_path):
    review = Review.model_validate({"events": [ev(2, "противник атакував 181 ударним БПЛА")]})
    records, _ = review_a2.to_records(review, AF_TEXT, data("af"))
    path = tmp_path / "dev" / "af-2026-08-03__FULL__pass1.jsonl"
    review_a2.save(path, records, "m")
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["label_method"] == "review-a2-v1" and row["prelabel"] is None
    assert row["reviewer"] == "m"


def test_gold_path_and_prompt():
    assert review_a2.gold_path("af", "2026-07-21", "dev").name == "af-2026-07-21__FULL__pass1.jsonl"
    prompt = review_a2.build_prompt(AF_TEXT)
    assert "[3] ППО збила" in prompt
    assert "Russian" in review_a2.system_prompt("rumod")
