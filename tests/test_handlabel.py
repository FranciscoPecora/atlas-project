import json

from src.handlabel import (
    direction_chips,
    english_directions,
    items_for,
    key_span,
    out_path,
    place_chips,
    report_records,
    sentence_at,
    to_record,
)
from src.prelabel import paragraph_spans

# Invented sentences, not report text.
TEXT = (
    "Заголовок звіту\n\n"
    "На Лиманському напрямку ворог атакував 5 разів у районі Ясного та Новий Комар. "
    "Авіаудару зазнав Комар.\n\n"
    "На Курському і Сумському напрямках відбулося 3 боєзіткнення."
)
NAMES = {"Ясного": "Yasne", "Комар": "Komar", "Новий Комар": "Novyi Komar", "Лиман": "Lyman"}
AID = {
    "translation": "[1] starts: Заголовок\nReport title\n\n"
    "[2] starts: На Лиманському\nIn the Lyman direction the enemy attacked 5 times near "
    "Yasne and Novyi Komar. Komar was hit by an air strike.\n\n"
    "[3] starts: На Курському\nIn the Kursk and Sumy directions there were 3 clashes.",
    "places": "\n".join(f"{k} = {v}" for k, v in NAMES.items()),
}
DATA = {
    "report_id": "gsu-2026-07-21",
    "source": "gsu",
    "report_date": "2026-07-21",
    "sector": "FULL",
    "text_sha256": "abc",
    "source_url": "https://example.org/r",
}
PARAS = paragraph_spans(TEXT)


def key_of(word: str, nth: int = 0) -> str:
    at = -1
    for _ in range(nth + 1):
        at = TEXT.index(word, at + 1)
    return f"{at}-{at + len(word)}"


def test_key_span():
    assert key_span("120-131") == (120, 131)


def test_place_chips_whole_words_longest_first_in_text_order():
    chips = place_chips(TEXT, *PARAS[1], NAMES)
    assert [c["en"] for c in chips] == ["Yasne", "Novyi Komar", "Komar"]  # no Lyman, no 2nd Komar
    assert chips[2]["key"] == key_of("Комар", 1)  # the stand-alone one, not inside "Новий Комар"


def test_direction_chips_split_two_directions():
    assert [c["uk"] for c in direction_chips(TEXT, *PARAS[2], NAMES)] == ["Курському", "Сумському"]
    assert [c["uk"] for c in direction_chips(TEXT, *PARAS[1], NAMES)] == ["Лиманському"]
    assert direction_chips(TEXT, *PARAS[0], NAMES) == []


def test_items_hold_english_and_buttons_but_no_answer():
    items = items_for("gsu-2026-07-21", TEXT, AID)
    assert [i["id"] for i in items] == ["gsu-2026-07-21:1", "gsu-2026-07-21:2", "gsu-2026-07-21:3"]
    assert items[1]["english"].startswith("In the Lyman direction")
    assert len(items[1]["places"]) == 3 and len(items[2]["directions"]) == 2
    assert "event_type" not in json.dumps(items)


def test_sentence_at_picks_the_sentence_of_the_place():
    s, e = sentence_at(TEXT, *PARAS[1], key_span(key_of("Комар", 1))[0])
    assert TEXT[s:e] == "Авіаудару зазнав Комар."


def test_to_record_fills_place_offsets_date_and_sides():
    event = {"event_type": "air_strike", "actor": "RU", "place": key_of("Комар", 1)}
    record, problem = to_record(event, TEXT, PARAS[1], DATA)
    assert problem is None
    assert record["location_text"] == "Комар" and record["geo_precision"] == 2
    assert TEXT[record["evidence_start"] : record["evidence_end"]] == "Авіаудару зазнав Комар."
    assert record["event_date"] == "2026-07-20" and record["epistemic_status"] == "ua_claimed"
    assert (record["actor"], record["target"]) == ("RU", "UA")
    assert "evidence_quote" not in record


def test_to_record_ukrainian_actor_and_no_place_use_the_paragraph():
    event = {"event_type": "other", "actor": "UA", "place": None, "quantity": 3}
    record, _ = to_record(event, TEXT, PARAS[2], DATA)
    assert (record["actor"], record["target"]) == ("UA", "RU")
    assert record["location_text"] is None and record["geo_precision"] is None
    assert (record["evidence_start"], record["evidence_end"]) == PARAS[2]


def test_to_record_reports_what_code_cannot_place():
    bad_count = {"event_type": "shelling", "place": key_of("Ясного"), "quantity": 77}
    assert to_record(bad_count, TEXT, PARAS[1], DATA) == (None, "count 77 is not in the paragraph")
    typed = {"event_type": "shelling", "place": "free:Somewhere"}
    assert "typed by hand" in to_record(typed, TEXT, PARAS[1], DATA)[1]
    assert "unknown event type" in to_record({"event_type": "x"}, TEXT, PARAS[1], DATA)[1]
    outside = {"event_type": "shelling", "place": key_of("Курському")}
    assert "outside" in to_record(outside, TEXT, PARAS[1], DATA)[1]


def test_report_records_count_progress_minutes_and_problems():
    answers = {
        "gsu-2026-07-21:1": {"done": True, "seconds": 30, "events": []},
        "gsu-2026-07-21:2": {
            "done": True,
            "seconds": 90,
            "events": [
                {"event_type": "ground_assault", "actor": "RU", "place": key_of("Ясного")},
                {"event_type": "shelling", "place": "free:Somewhere"},
            ],
        },
    }
    records, problems, facts = report_records(answers, TEXT, DATA)
    assert len(records) == 1 and records[0]["minutes"] == 2.0
    assert len(problems) == 1 and "paragraph 2" in problems[0]
    assert (facts["paragraphs"], facts["done"], facts["minutes"]) == (3, 2, 2.0)
    assert [d["paragraph"] for d in facts["dropped"]] == [2]


def test_out_path_is_outside_the_gold_folder(tmp_path):
    path = out_path("gsu-2026-07-21", tmp_path)
    assert path.name == "gsu-2026-07-21__FULL__human1.jsonl"
    assert "gold" not in out_path("gsu-2026-07-21").parts


def test_english_directions_come_from_the_opening_words():
    assert english_directions("In the Kursk and Sumy directions there were", 2) == ["Kursk", "Sumy"]
    assert english_directions("In the Lyman direction the enemy", 1) == ["Lyman"]
    assert english_directions("On the Volyn and Polissia axes, no signs", 2) == [
        "Volyn",
        "Polissia",
    ]
    assert english_directions("Over the past day", 1) == [None]
    assert english_directions("In the Kursk and Sumy directions", 1) == [None]  # counts differ


def test_items_name_directions_in_english():
    items = items_for("gsu-2026-07-21", TEXT, AID)
    assert [d["en"] for d in items[2]["directions"]] == ["Kursk", "Sumy"]


def test_report_records_lists_events_it_could_not_import():
    text = "Ворог атакував поблизу Яблунівки."
    data = {"report_id": "gsu-x", "source": "gsu", "report_date": "2026-01-02", "sector": "FULL",
            "text_sha256": "0", "source_url": "u"}  # fmt: skip
    answers = {"gsu-x:1": {"done": True, "seconds": 5, "events": [
        {"event_type": "ground_assault", "actor": "RU", "place": "free:Somewhere", "quantity": None}
    ]}}  # fmt: skip
    records, problems, facts = report_records(answers, text, data)
    assert records == [] and len(problems) == 1
    assert facts["dropped"][0]["paragraph"] == 1
