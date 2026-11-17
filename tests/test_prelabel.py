"""Invented sentences in GSU style. Real report text is never committed."""

from src.prelabel import (
    VERSION,
    event_date,
    paragraph_spans,
    places,
    prefill_report,
    to_int,
    to_prediction,
)

REPORT = (
    "Заголовок про 100 боєзіткнень\n\n"
    "Протягом минулої доби відбулося 100 бойових зіткнень.\n\n"
    "На Північному напрямку минулої доби відбулося одне боєзіткнення, агресор завдав "
    "трьох авіаударів, здійснив 40 обстрілів позицій наших військ.\n\n"
    "На Зеленому напрямку ворог тричі атакував у районах Нової Балки, Кам’янки та в бік "
    "населених пунктів Рай-Гірки й Вишневого.\n\n"
    "На Синьому напрямку зафіксовано сім атак. Окупанти вели штурмові дії в районі Ясного.\n\n"
    "На Тихому напрямку минулої доби ворог наступальних дій не проводив.\n"
)


def by_location(text: str) -> dict[str, tuple[str, int | None]]:
    return {p.location_text: (p.event_type, p.quantity) for p in prefill_report(text)}


def test_one_event_per_place_with_exact_inflection():
    found = by_location(REPORT)
    for name in ("Нової Балки", "Кам’янки", "Рай-Гірки", "Вишневого", "Ясного"):
        assert found[name][0] == "ground_assault"
    # a count shared by several places belongs to none of them
    assert found["Нової Балки"][1] is None
    # the only place in its paragraph takes the paragraph's count
    assert found["Ясного"] == ("ground_assault", 7)


def test_direction_level_events_when_no_place_is_named():
    found = [p for p in prefill_report(REPORT) if p.location_text == "Північному напрямку"]
    assert {(p.event_type, p.quantity) for p in found} == {
        ("ground_assault", 1),
        ("air_strike", 3),
        ("shelling", 40),
    }


def test_headline_totals_and_negative_paragraphs_give_nothing():
    found = by_location(REPORT)
    assert "Тихому напрямку" not in found
    assert all("100" not in (k or "") for k in found)
    assert len(found) == 6  # 5 places + the North direction (3 kinds share one key)


def test_evidence_span_is_the_sentence_holding_the_place():
    text = REPORT
    p = next(x for x in prefill_report(text) if x.location_text == "Ясного")
    assert text[p.start : p.end] == "Окупанти вели штурмові дії в районі Ясного."
    assert "Ясного" in text[p.start : p.end]


def test_places_only_after_markers():
    s = "На Зеленому напрямку ворог атакував у напрямку Великої Ріки. Ворог відступив."
    assert [n for _, _, n in places(s, 0, len(s))] == ["Великої Ріки"]


def test_count_words():
    assert [to_int(w) for w in ("тричі", "сім", "одне", "один", "10 408", "чотирнадцять")] == [
        3,
        7,
        1,
        1,
        10408,
        14,
    ]
    assert to_int("ворог") is None


def test_paragraph_spans_are_trimmed():
    assert [REPORT[a:b][:9] for a, b in paragraph_spans(REPORT)][:2] == ["Заголовок", "Протягом "]


def test_prediction_is_label_studio_shaped_and_offsets_are_unit_relative():
    unit_start = REPORT.index("На Зеленому")
    unit_text = REPORT[unit_start:]
    data = {"text": unit_text, "unit_start": unit_start, "report_date": "2026-07-21"}
    pred = to_prediction(prefill_report(REPORT), data)
    assert pred["model_version"] == VERSION
    labels = [r for r in pred["result"] if r["type"] == "labels"]
    assert len(labels) == 5  # North direction lies before the unit and is left out
    for r in labels:
        v = r["value"]
        assert unit_text[v["start"] : v["end"]] == v["text"]
    dates = {r["value"]["text"][0] for r in pred["result"] if r["from_name"] == "event_date"}
    assert dates == {event_date("2026-07-21")} == {"2026-07-20"}
    ids = {r["id"] for r in pred["result"]}
    assert len(ids) == 5  # every field of one event shares its region id
