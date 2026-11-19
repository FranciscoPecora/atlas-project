from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from src.audit_fields import (
    QuoteTranslations,
    audit_dates,
    draw,
    read_marks,
    rows,
    translate_quotes,
    unsupported_rate,
    write_csv,
)

SPEC_ROWS = "\n".join(
    f"| {i} | {d} | {s} | {sec} | {split} |"
    for i, (d, s, sec, split) in enumerate(
        [("2026-07-19", "ISW", "AIR", "dev"), ("2026-07-21", "GSU", "FULL", "dev"),
         ("2026-07-23", "ISW", "OSKIL", "dev")]
        + [(str(date(2026, 8, 1) + timedelta(days=d)), "GSU", "FULL", "test") for d in range(42)],
        1,
    )
)  # fmt: skip


def test_audit_dates_are_dev_period_gsu_reports_not_in_gold(tmp_path):
    folder = tmp_path / "text" / "gsu"
    folder.mkdir(parents=True)
    for d in ("2026-07-18", "2026-07-19", "2026-07-20", "2026-07-21", "2026-07-23", "2026-07-24"):
        (folder / f"{d}.txt").write_text("x")
    # 19 and 23 are ISW gold dates (the GSU report of that day is not gold); 21 is GSU gold.
    assert audit_dates(SPEC_ROWS, tmp_path) == ["2026-07-19", "2026-07-20", "2026-07-23"]


def test_draw_is_seeded_and_sorted():
    records = [{"report_id": f"r{i % 3}", "position": i} for i in range(30)]
    a, b = draw(records, 5, 7), draw(records, 5, 7)
    assert a == b and len(a) == 5
    assert a == sorted(a, key=lambda r: (r["report_id"], r["position"]))
    assert len(draw(records, 99, 7)) == 30


def record(**kw):
    base = {"report_id": "gsu-2026-07-20", "position": 4, "report_date": "2026-07-20",
            "default_date": "2026-07-19", "event_type": "shelling", "epistemic_status":
            "ua_claimed", "location_text": "Alfa", "quantity": None, "units": [],
            "evidence_quote": "Invented quote about Alfa."}  # fmt: skip
    return {**base, **kw}


def test_rows_show_the_quote_its_english_and_only_non_empty_fields():
    (row,) = rows([record()], {"Invented quote about Alfa.": "English"})
    assert row["record_id"] == "gsu-2026-07-20:4" and row["quote_en"] == "English"
    assert row["location_text"] == "Alfa" and row["quantity"] == "" and row["units"] == ""
    assert row["checked"] == "" and row["unsupported_fields"] == ""


def test_marks_skip_unchecked_rows_and_reject_unknown_fields(tmp_path):
    path = tmp_path / "a.csv"
    write_csv(path, [
        {"record_id": "a:1", "checked": "x", "unsupported_fields": "quantity, actor"},
        {"record_id": "a:2", "checked": "x", "unsupported_fields": ""},
        {"record_id": "a:3", "checked": "", "unsupported_fields": "quantity"},
    ])  # fmt: skip
    assert read_marks(path) == {"a:1": {"quantity", "actor"}, "a:2": set()}
    write_csv(path, [{"record_id": "a:1", "checked": "x", "unsupported_fields": "colour"}])
    with pytest.raises(ValueError):
        read_marks(path)


def test_rate_counts_only_fields_the_system_kept():
    marks = {"a:1": {"quantity"}, "a:2": set(), "a:3": {"location_text"}}
    s2 = {"a:1": {"event_type", "quantity"}, "a:2": {"event_type"}, "a:3": {"location_text"}}
    assert unsupported_rate(marks, s2) == (2, 4)
    verified = {"a:1": {"event_type"}, "a:2": {"event_type"}, "a:3": set()}  # 3 was dropped
    assert unsupported_rate(marks, verified) == (0, 2)


def test_translate_quotes_checks_the_count():
    def parse(**kw):
        return SimpleNamespace(stop_reason="end_turn",
                               parsed_output=QuoteTranslations(english=["one"]))  # fmt: skip

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    models = {"translation": "m", "translation_effort": "low"}
    assert translate_quotes(client, models, ["a"]) == ["one"]
    with pytest.raises(ValueError):
        translate_quotes(client, models, ["a", "b"])


def test_latin_spelling_lets_a_reader_find_the_name():
    from src.audit_fields import latin

    assert latin("Ізбицького") == "Izbytskoho"
    assert latin("Юнаківка та Яблунівка") == "Yunakivka ta Yablunivka"
    assert latin("Слов’янськ") == "Sloviansk"


def test_page_answers_skip_unsure_and_reject_unknown_fields(tmp_path):
    import json

    from src.audit_fields import read_answers

    path = tmp_path / "a.json"
    answers = {"a:1": {"unsure": False, "unsupported": ["quantity"]},
               "a:2": {"unsure": False, "unsupported": []},
               "a:3": {"unsure": True, "unsupported": []}}  # fmt: skip
    path.write_text(json.dumps({"kind": "fields", "answers": answers}))
    assert read_answers(path) == {"a:1": {"quantity"}, "a:2": set()}
    path.write_text(json.dumps({"kind": "places", "answers": {}}))
    with pytest.raises(ValueError):
        read_answers(path)
    answers["a:1"]["unsupported"] = ["colour"]
    path.write_text(json.dumps({"kind": "fields", "answers": answers}))
    with pytest.raises(ValueError):
        read_answers(path)


def test_page_holds_the_items_and_cannot_be_broken_by_text():
    from src.audit_fields import render_page

    html = render_page([{"id": "a", "quote_en": "x </script> y"}], "<p>/*ITEMS*/[]</p>")
    assert "</script>" not in html and '"id": "a"' in html


def test_over_removed_counts_fields_the_annotator_called_supported():
    from src.audit_fields import over_removed

    marks = {"r:1": {"quantity"}, "r:2": set()}
    before = {"r:1": {"event_type", "quantity"}, "r:2": {"event_type", "actor"}}
    after = {"r:1": {"event_type"}, "r:2": {"event_type"}}
    assert over_removed(marks, before, after) == (1, 2)  # actor removed but was fine


def test_bootstrap_interval_contains_the_rate_and_is_seeded():
    from src.audit_fields import bootstrap_rate

    marks = {f"rep{i}:{j}": ({"quantity"} if i == 0 else set()) for i in range(5) for j in range(4)}
    kept = {k: {"event_type", "quantity"} for k in marks}
    low, high = bootstrap_rate(marks, kept, 500, 1)
    assert low <= 0.1 <= high and (low, high) == bootstrap_rate(marks, kept, 500, 1)
