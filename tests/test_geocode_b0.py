import json

import pytest

from eval.score import accuracy, append_results, load_gold
from src.baselines import b0_regex
from src.gazetteer import Gazetteer, Place
from src.geocode import geocode, paragraph_at

TEXT = (
    "Заголовок звіту\n\n"
    "На Лиманському напрямку ворог атакував 5 разів у районі Ясного.\n\n"
    "На Покровському напрямку відбулося 7 боєзіткнень."
)


def place(id_, name, lat, lon, uk, oblast="Donetsk", pop=0):
    return Place(id_, name, lat, lon, oblast, pop, "PPL", (name, uk))


LYMAN = place("gn:1", "Lyman", 48.99, 37.80, "Лиман", pop=20000)
POKROVSK = place("gn:2", "Pokrovsk", 48.28, 37.18, "Покровськ", pop=60000)
YASNE = place("gn:3", "Yasne", 49.05, 37.90, "Ясне")
YASNE_FAR = place("gn:4", "Yasne", 52.12, 32.99, "Ясне", "Chernihiv", 500)
GAZ = Gazetteer([LYMAN, POKROVSK, YASNE, YASNE_FAR])
CFG = {
    "direction_anchors": {
        "Лиманський": ["Лиман", "Donetsk"],
        "Покровський": ["Покровськ", "Donetsk"],
    },
    "max_anchor_km": 120,
}


def test_b0_extracts_place_and_direction_events_without_coordinates():
    events = b0_regex.extract(TEXT, "gsu-2026-07-21", "2026-07-21")
    assert [(e["event_type"], e["location_text"], e["quantity"]) for e in events] == [
        ("ground_assault", "Ясного", 5),
        ("ground_assault", "Покровському напрямку", 7),
    ]
    assert all(e["event_date"] == "2026-07-20" and e["sector"] == "FULL" for e in events)
    assert all("lat" not in e for e in events)
    assert len({e["id"] for e in events}) == 2


def test_geocode_uses_the_paragraph_direction_and_direction_towns():
    events = b0_regex.extract(TEXT, "gsu-2026-07-21", "2026-07-21")
    village, direction = geocode(events, TEXT, GAZ, CFG)
    assert village["gazetteer_id"] == "gn:3" and village["geocode_how"] == "stem"
    assert direction["gazetteer_id"] == "gn:2" and direction["geocode_how"] == "direction"


def test_geocode_leaves_unknown_and_missing_places_without_coordinates():
    base = {"evidence_start": TEXT.index("На Лиманському")}
    unknown, none = geocode(
        [{**base, "location_text": "Атлантиди"}, {**base, "location_text": None}], TEXT, GAZ, CFG
    )
    assert unknown["lat"] is None and unknown["geocode_how"] == "none"
    assert none["lat"] is None and none["geocode_how"] == "no_place"


def test_paragraph_at():
    assert paragraph_at(TEXT, TEXT.index("Ясного")).startswith("На Лиманському")
    assert paragraph_at(TEXT, 10_000) == ""


def test_accuracy_over_matched_pairs():
    pairs = [({"quantity": 5}, {"quantity": 5}), ({"quantity": 1}, {"quantity": None})]
    assert accuracy(pairs, "quantity") == (0.5, 2)
    assert accuracy(pairs, "quantity", only_gold_set=True) == (1.0, 1)
    assert accuracy([], "quantity") == (None, 0)


def test_load_gold_refuses_test_split_outside_make_eval_test(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_EVAL_TEST", raising=False)
    with pytest.raises(PermissionError):
        load_gold("test", tmp_path)
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "gsu-2026-07-21__FULL__pass1.jsonl").write_text(
        json.dumps({"event_type": "shelling"}) + "\n", encoding="utf-8"
    )
    gold = load_gold("dev", tmp_path)
    assert gold[0]["id"] == "gsu-2026-07-21__FULL__pass1:gold:0"


def test_append_results_writes_header_once(tmp_path):
    path = tmp_path / "results.csv"
    row = {"commit": "abc", "system": "B0", "metric": "event_f1", "value": 0.5}
    append_results([row], path)
    append_results([row], path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("commit,config_hash") and len(lines) == 3
