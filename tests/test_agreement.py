"""Human pass against the key. Invented sentences only."""

from src.agreement import (
    collapse,
    compare,
    direction_phrase,
    pair_unit,
    paragraph_of,
    summary,
    unit,
    units,
)
from src.prelabel import paragraph_spans

TEXT = (
    "На Вигаданому і Тестовому напрямках ворог завдав трьох авіаційних ударів.\n\n"
    "На Зразковому напрямку ворог атакував у районах Яблунівки та Грушівки.\n\n"
    "Сили оборони уразили два пункти управління."
)
SPANS = paragraph_spans(TEXT)


def ev(kind: str, place: str | None, para: int, quantity: int | None = None, actor: str = "RU"):
    return {"event_type": kind, "location_text": place, "evidence_start": SPANS[para - 1][0],
            "quantity": quantity, "actor": actor, "report_id": "gsu-x"}  # fmt: skip


def test_paragraph_of_finds_the_paragraph_or_zero():
    assert paragraph_of(SPANS, SPANS[1][0] + 3) == 2
    assert paragraph_of(SPANS, 10**6) == 0


def test_direction_phrase_is_empty_without_a_direction():
    assert direction_phrase("На Вигаданому і Тестовому напрямках ворог") != ""
    assert direction_phrase("Сили оборони уразили два пункти.") == ""


def test_unit_tells_direction_place_and_no_place_apart():
    assert unit(ev("air_strike", "Вигаданому", 1), TEXT, SPANS) == (1, "direction", "")
    assert unit(ev("air_strike", "Вигаданому і Тестовому напрямках", 1), TEXT, SPANS) == (
        1, "direction", "")  # fmt: skip
    assert unit(ev("ground_assault", "Яблунівки", 2), TEXT, SPANS) == (2, "place", "Яблунівки")
    assert unit(ev("other", None, 3), TEXT, SPANS) == (3, "none", "")


def test_a_village_whose_name_starts_like_the_direction_is_a_place():
    assert unit(ev("ground_assault", "Зразков", 2), TEXT, SPANS)[1] == "place"


def test_collapse_keeps_one_event_per_type_and_prefers_a_count():
    out = collapse([ev("air_strike", "Вигаданому", 1), ev("air_strike", "Тестовому", 1, 3),
                    ev("shelling", "Вигаданому", 1)])  # fmt: skip
    assert [(e["event_type"], e["quantity"]) for e in out] == [
        ("air_strike", 3),
        ("shelling", None),
    ]


def test_units_collapse_directions_only():
    two = [ev("ground_assault", "Яблунівки", 2), ev("ground_assault", "Яблунівки", 2)]
    assert len(units(two, TEXT)[(2, "place", "Яблунівки")]) == 2
    both = [ev("air_strike", "Вигаданому", 1), ev("air_strike", "Тестовому", 1)]
    assert len(units(both, TEXT)[(1, "direction", "")]) == 1


def test_pair_unit_pairs_same_type_first_then_the_rest():
    h = [ev("missile_strike", None, 3), ev("other", None, 3)]
    k = [ev("other", None, 3), ev("air_strike", None, 3), ev("shelling", None, 3)]
    pairs, only_h, only_k = pair_unit(h, k)
    assert [(a["event_type"], b["event_type"]) for a, b in pairs] == [
        ("other", "other"), ("missile_strike", "air_strike")]  # fmt: skip
    assert only_h == [] and [e["event_type"] for e in only_k] == ["shelling"]


def test_compare_counts_pairs_and_leftovers():
    human = [ev("air_strike", "Вигаданому", 1, 3), ev("ground_assault", "Яблунівки", 2)]
    key = [ev("air_strike", "Вигаданому", 1), ev("air_strike", "Тестовому", 1),
           ev("ground_assault", "Яблунівки", 2), ev("ground_assault", "Грушівки", 2)]  # fmt: skip
    res = compare(human, key, TEXT)
    assert len(res["pairs"]) == 2 and res["human_only"] == []
    assert [e["location_text"] for e, _ in res["key_only"]] == ["Грушівки"]


def test_summary_rates():
    pairs = [(ev("air_strike", None, 1, 3), ev("air_strike", None, 1)),
             (ev("shelling", None, 1), ev("ground_assault", None, 1))]  # fmt: skip
    s = summary(pairs, human_only=1, key_only=2)
    assert (s["human_events"], s["key_events"], s["paired"]) == (3, 4, 2)
    assert s["type_same"] == 1 and s["pairs_with_a_count"] == 1 and s["count_same"] == 0
    assert round(s["event_precision"], 3) == 0.667 and s["event_recall"] == 0.5
