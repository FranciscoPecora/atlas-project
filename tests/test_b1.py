from src.baselines import b1_gliner

TEXT = (
    "Заголовок звіту\n\n"
    "На Лиманському напрямку ворог атакував у районі Ясного та Діброви. "
    "Противник завдав авіаудару по Ясному.\n\n"
    "Погода у Харкові сонячна."
)


class FakeModel:
    """Stands in for GLiNER2: tags fixed words as settlements."""

    WORDS = ("Ясного", "Діброви", "Ясному", "Харкові")

    def __init__(self):
        self.calls = []

    def extract_entities(self, text, labels, threshold, include_spans, include_confidence):
        self.calls.append((labels, threshold))
        hits = [
            {"text": w, "start": text.index(w), "end": text.index(w) + len(w), "confidence": 0.9}
            for w in self.WORDS
            if w in text
        ]
        return {"entities": {"settlement": hits}}


def test_event_types_first_keyword_rule_wins():
    assert b1_gliner.event_types("ворог атакував у районі") == ["ground_assault"]
    assert b1_gliner.event_types("завдав авіаудару") == ["air_strike"]
    assert b1_gliner.event_types("здійснив 5 обстрілів") == ["shelling"]
    assert b1_gliner.event_types("Погода сонячна.") == []


def test_extract_makes_one_event_per_settlement_and_type():
    model = FakeModel()
    events = b1_gliner.extract(model, TEXT, "gsu-2026-07-21", "2026-07-21", threshold=0.5)
    got = [(e["event_type"], e["location_text"]) for e in events]
    assert got == [
        ("ground_assault", "Ясного"),
        ("ground_assault", "Діброви"),
        ("air_strike", "Ясному"),
    ]
    first = events[0]
    assert TEXT[first["evidence_start"] : first["evidence_end"]].endswith("Діброви.")
    assert first["event_date"] == "2026-07-20" and first["system"] == "B1"
    assert model.calls[0] == (b1_gliner.LABELS, 0.5)


def test_paragraph_without_event_keyword_gives_nothing():
    events = b1_gliner.extract(FakeModel(), TEXT, "gsu-2026-07-21", "2026-07-21", 0.5)
    assert all(e["location_text"] != "Харкові" for e in events)
