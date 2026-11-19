import csv
import math

import pytest

from src.gazetteer import Gazetteer, Place
from src.geocode_check import (
    candidates,
    english_paragraph,
    errors_km,
    read_picks,
    row,
    sample_places,
    summary,
)


def place(id_, lat, lon, pop=0):
    return Place(id_, "Alfa", lat, lon, "Donetsk", pop, "PPL", ("Alfa", "Альфа"))


TOWN = Place("gn:t", "Town", 48.0, 37.0, "Donetsk", 9, "PPL", ("Town", "Місто"))
A2, A1, FAR = place("gn:2", 48.1, 37.0), place("gn:1", 48.5, 37.0, 50), place("gn:3", 51, 33, 900)
GAZ = Gazetteer([TOWN, A1, A2, FAR])


def test_english_paragraph_reads_one_numbered_block():
    stored = (
        "[1] starts: a …\nFirst.\n\n[2] starts: b …\nSecond line.\n\n[12] starts: c …\nTwelfth."
    )
    assert english_paragraph(stored, 2) == "Second line."
    assert english_paragraph(stored, 12) == "Twelfth." and english_paragraph(stored, 5) == ""


def test_candidates_are_near_the_town_in_id_order_or_largest_without_one():
    assert [c.gazetteer_id for c in candidates(GAZ, "Альфа", TOWN, 120)] == ["gn:1", "gn:2"]
    assert [c.gazetteer_id for c in candidates(GAZ, "Альфа", None, 120)] == ["gn:1", "gn:2",
                                                                            "gn:3"]  # fmt: skip


def test_row_does_not_show_the_geocoder_choice(tmp_path):
    item = {"name": "Альфа", "direction": "Мiському напрямку", "english": "Alfa"}
    r = row(item, [A1, A2], TOWN)
    assert r["ids"] == "gn:1 gn:2" and r["pick"] == ""
    assert "geocode" not in " ".join(r) and "openstreetmap" in r["row_B"]


def test_read_picks_maps_letters_to_ids_and_skips_unsure(tmp_path):
    path = tmp_path / "c.csv"
    rows = [{"place_id": "a", "ids": "gn:1 gn:2", "pick": "b"},
            {"place_id": "b", "ids": "gn:1", "pick": "none"},
            {"place_id": "c", "ids": "gn:1", "pick": "?"},
            {"place_id": "d", "ids": "gn:1", "pick": ""}]  # fmt: skip
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["place_id", "ids", "pick"])
        w.writeheader()
        w.writerows(rows)
    assert read_picks(path) == {"a": "gn:2", "b": None}
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["place_id", "ids", "pick"])
        w.writeheader()
        w.writerow({"place_id": "a", "ids": "gn:1", "pick": "C"})
    with pytest.raises(ValueError):
        read_picks(path)


def test_errors_and_summary():
    events = [
        {"place_id": "a", "lat": 48.1, "lon": 37.0},
        {"place_id": "a", "lat": 48.5, "lon": 37.0},
        {"place_id": "a", "lat": None},
        {"place_id": "z", "lat": 1},
    ]
    errs = errors_km(events, {"a": A2})
    assert errs[0] == 0 and 40 < errs[1] < 50 and math.isinf(errs[2]) and len(errs) == 3
    acc, med, n = summary(errs)
    assert (round(acc, 3), n) == (0.333, 3) and 40 < med < 50
    assert summary([]) == (None, None, 0)


def test_sample_is_seeded_distinct_and_sorted():
    items = [{"name": n, "direction": d} for n in "abcdef" for d in ("x", None)] * 2
    s = sample_places(items, 4, 1)
    assert s == sample_places(items, 4, 1) and len(s) == 4
    keys = [(i["name"], i["direction"] or "") for i in s]
    assert keys == sorted(set(keys))


def test_page_item_and_saved_answers(tmp_path):
    import json

    from src.geocode_check import page_item, read_answers

    item = page_item({"name": "Альфа", "direction": "x", "english": "Alfa"}, [A2], TOWN)
    assert item["id"] == "Альфа|x" and item["cands"][0]["km"] == 11
    assert item["town"]["name"] == "Town"
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"kind": "places", "answers": {"a": "gn:1", "b": "none",
                                                              "c": "unsure"}}))  # fmt: skip
    assert read_answers(path) == {"a": "gn:1", "b": None}
