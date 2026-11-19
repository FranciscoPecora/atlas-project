from types import SimpleNamespace

from src.gazetteer import Gazetteer, Place
from src.geocode import (
    Choice,
    chooser_prompt,
    disambiguate,
    geocode,
    model_chooser,
    paragraph_oblasts,
    same_direction,
)


def place(id_, lat, lon, oblast="Donetsk", pop=0, kind="PPL", name="Alfa", uk="Альфа"):
    return Place(id_, name, lat, lon, oblast, pop, kind, (name, uk))


TOWN = place("gn:t", 48.0, 37.0, name="Town", uk="Місто")
NEAR = place("gn:1", 48.1, 37.0)  # about 11 km from the town
MID = place("gn:2", 48.5, 37.0)  # about 56 km
FAR = place("gn:3", 51.0, 33.0, "Sumy", 900)  # far beyond 120 km


def test_oblasts_come_from_a_fixed_list_not_from_any_shchyna_word():
    text = "Ворог атакував у Сумській області та на Харківщині, біля Яструбщини."
    assert paragraph_oblasts(text) == {"Sumy", "Kharkiv"}
    assert paragraph_oblasts("Без області тут.") == set()


def test_rule_order():
    assert disambiguate([], set(), TOWN, 120, []) == (None, "no_match", [])
    assert disambiguate([FAR], set(), None, 120, [])[1] == "unique"
    assert disambiguate([NEAR, FAR], {"Sumy"}, None, 120, [])[:2] == (FAR, "oblast")
    assert disambiguate([NEAR, FAR], set(), TOWN, 120, [])[:2] == (NEAR, "direction")
    assert disambiguate([FAR], set(), TOWN, 120, [])[:2] == (None, "too_far")
    # Two candidates near the town: the previous day's events decide before distance.
    assert disambiguate([NEAR, MID], set(), TOWN, 120, [(48.5, 37.01)])[:2] == (
        MID, "previous_day")  # fmt: skip
    assert disambiguate([NEAR, MID], set(), TOWN, 120, [])[:2] == (NEAR, "nearest_town")
    assert disambiguate([NEAR, FAR], set(), None, 120, [])[:2] == (FAR, "population")


def test_population_prefers_settlements_over_areas():
    raion = place("gn:9", 48.2, 37.0, pop=99999, kind="ADM2")
    assert disambiguate([raion, MID], set(), None, 120, [])[0] == MID


def test_same_direction_compares_stems():
    assert same_direction("Покровському напрямку", "Покровський напрямок")
    assert not same_direction("Покровському напрямку", "Лиманському напрямку")
    assert not same_direction(None, "Лиманському напрямку")


TEXT = "Заголовок\n\nНа Покровському напрямку ворог атакував у районі Альфи."
CFG = {"direction_anchors": {"Покровський": ["Town", "Donetsk"]}, "max_anchor_km": 120}
GAZ = Gazetteer([TOWN, NEAR, MID, FAR])
EVENT = {"location_text": "Альфи", "evidence_start": TEXT.index("На")}


def test_geocode_logs_the_rule_and_uses_previous_day_on_the_same_direction():
    (e,) = geocode([EVENT], TEXT, GAZ, CFG)
    assert (e["gazetteer_id"], e["geocode_rule"]) == ("gn:1", "nearest_town")
    assert e["direction"] == "Покровському напрямку"
    previous = [{"lat": 48.5, "lon": 37.0, "direction": "Покровському напрямку"},
                {"lat": 48.1, "lon": 37.0, "direction": "Лиманському напрямку"}]  # fmt: skip
    (e,) = geocode([EVENT], TEXT, GAZ, CFG, previous=previous)
    assert (e["gazetteer_id"], e["geocode_rule"]) == ("gn:2", "previous_day")


def test_chooser_is_asked_only_for_weak_rules_and_may_decline():
    asked = []

    def chooser(event, cands, town):
        asked.append([c.gazetteer_id for c in cands])
        return cands[-1]

    (e,) = geocode([EVENT], TEXT, GAZ, CFG, chooser=chooser)
    assert asked == [["gn:1", "gn:2"]]
    assert (e["gazetteer_id"], e["geocode_rule"]) == ("gn:2", "model")
    previous = [{"lat": 48.1, "lon": 37.0, "direction": "Покровському напрямку"}]
    geocode([EVENT], TEXT, GAZ, CFG, previous=previous, chooser=chooser)
    assert len(asked) == 1  # previous_day is not weak
    (e,) = geocode([EVENT], TEXT, GAZ, CFG, chooser=lambda *a: None)
    assert e["geocode_rule"] == "nearest_town"


def test_model_chooser_accepts_only_listed_ids():
    replies = iter(["gn:2", "gn:404"])

    def parse(**kw):
        assert "id gn:1" in kw["messages"][0]["content"]
        return SimpleNamespace(stop_reason="end_turn", usage=None,
                               parsed_output=Choice(gazetteer_id=next(replies)))  # fmt: skip

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    log: list = []
    cfg = {"models": {"geocode_disambiguation": "m", "verifier_effort": "low"}}
    choose = model_chooser(client, cfg, log)
    assert choose(EVENT, [NEAR, MID], TOWN) == MID
    assert choose(EVENT, [NEAR, MID], TOWN) is None
    assert [x["picked"] for x in log] == ["gn:2", None]


def test_chooser_prompt_lists_rows_without_coordinates():
    text = chooser_prompt({**EVENT, "evidence_quote": "q"}, [NEAR, MID], TOWN)
    assert "gn:1" in text and "gn:2" in text and "48.1" not in text


def test_cached_chooser_asks_live_once_and_never_without_it():
    import pytest

    from src.geocode import cached_chooser

    calls = []
    cache: dict = {}
    live = cached_chooser(cache, lambda e, c, t: calls.append(1) or c[1])
    assert live(EVENT, [NEAR, MID], TOWN) == MID and live(EVENT, [NEAR, MID], TOWN) == MID
    assert len(calls) == 1 and cache == {"Альфи|gn:1,gn:2": "gn:2"}
    offline = cached_chooser(cache)
    assert offline(EVENT, [NEAR, MID], TOWN) == MID
    with pytest.raises(KeyError):
        offline(EVENT, [MID, NEAR], TOWN)
