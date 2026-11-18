"""Hard case 13 fix. Invented sentences only."""

import pytest

from src.keyfix import merge, two_directions

TEXT = "На Вигаданому і Тестовому напрямках ворог завдав трьох авіаційних ударів та 40 обстрілів."
SPAN = (0, len(TEXT))


def ev(kind: str, place: str | None, method: str = "rules+review-v1"):
    return {"event_type": kind, "location_text": place, "quantity": None, "evidence_start": 0,
            "evidence_end": len(TEXT), "label_method": method}  # fmt: skip


def test_two_directions_only_when_there_are_two():
    assert two_directions(TEXT) == ("Вигаданому і Тестовому напрямках", ["Вигаданому", "Тестовому"])
    assert two_directions("На Вигаданому напрямку ворог атакував.") is None
    assert two_directions("Ворог атакував.") is None


def test_merge_makes_one_event_per_type_with_the_count():
    records = [ev("air_strike", "Вигаданому"), ev("air_strike", "Тестовому"),
               ev("shelling", "Вигаданому"), ev("shelling", "Тестовому")]  # fmt: skip
    out = merge(records, TEXT, SPAN, {"air_strike": 3, "shelling": 40})
    assert [(r["event_type"], r["location_text"], r["quantity"]) for r in out] == [
        ("air_strike", "Вигаданому і Тестовому напрямках", 3),
        ("shelling", "Вигаданому і Тестовому напрямках", 40),
    ]
    assert out[0]["label_method"] == "rules+review-v1+case13"


def test_merge_leaves_other_events_and_already_merged_ones_alone():
    records = [
        ev("ground_assault", "Яблунівки"),
        ev("air_strike", "Вигаданому і Тестовому напрямках"),
    ]
    assert merge(records, TEXT, SPAN, {}) == records


def test_merge_refuses_a_count_that_is_not_in_the_text():
    with pytest.raises(ValueError, match="not in its evidence"):
        merge([ev("air_strike", "Вигаданому")], TEXT, SPAN, {"air_strike": 9})
    with pytest.raises(ValueError, match="no count listed"):
        merge([ev("air_strike", "Вигаданому")], TEXT, SPAN, {})
