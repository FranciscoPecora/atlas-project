import json

from src.gazetteer import (
    Gazetteer,
    Place,
    direction_anchor,
    merge,
    normalise,
    paragraph_direction,
    read_admin1,
    read_geonames,
    read_osm,
    read_table,
    resolve,
    stem,
    write_table,
)


def place(id_, name, lat, lon, oblast="Donetsk", pop=0, kind="PPL", aliases=()):
    return Place(id_, name, lat, lon, oblast, pop, kind, tuple(sorted({name, *aliases})))


POKROVSK = place("gn:1", "Pokrovsk", 48.28, 37.18, pop=60000, aliases=["Покровськ"])
LYMAN = place("gn:2", "Lyman", 48.99, 37.80, pop=20000, aliases=["Лиман"])
YASNE_NEAR = place("gn:3", "Yasne", 48.30, 37.30, aliases=["Ясне"])
YASNE_FAR = place("gn:4", "Yasne", 52.12, 32.99, "Chernihiv", pop=500, aliases=["Ясне"])
KRYVA = place("gn:5", "Kryva Luka", 48.87, 37.90, aliases=["Крива Лука"])
RAION = place("gn:6", "Lyman Raion", 49.0, 37.9, kind="ADM2", aliases=["Лиман"])
GAZ = Gazetteer([POKROVSK, LYMAN, YASNE_NEAR, YASNE_FAR, KRYVA, RAION])
ANCHORS = {"Покровський": ["Покровськ", "Donetsk"], "Лиманський": ["Лиман", "Donetsk"]}


def test_normalise_unifies_case_apostrophes_and_spaces():
    assert normalise("Куп’янськ  ") == normalise("куп'янськ")


def test_stem_maps_case_forms_to_one_key():
    assert stem("Ясного") == stem("Ясне")
    assert stem("Кривої Луки") == stem("Крива Лука")
    assert stem("Покровському напрямку") == stem("Покровськ")
    assert stem("Малих Щербаків") == stem("Малі Щербаки")


def test_lookup_exact_then_stem_then_fuzzy_then_none():
    assert GAZ.lookup("Покровськ")[0] == "exact"
    assert GAZ.lookup("Покровська") == ("stem", [POKROVSK])
    assert GAZ.lookup("Покровсьска")[0] == "fuzzy"
    assert GAZ.lookup("Атлантида") == ("none", [])


def test_lookup_prefers_towns_over_areas_and_population_without_anchor():
    assert GAZ.lookup("Лиман")[1][0] == LYMAN
    assert GAZ.lookup("Ясного")[1][0] == YASNE_FAR


def test_direction_anchor_picks_the_nearest_namesake():
    near = direction_anchor(GAZ, "Покровському напрямку", ANCHORS)
    assert near == (POKROVSK.lat, POKROVSK.lon)
    how, found, km = resolve(GAZ, "Ясного", near, max_km=120)
    assert (how, found) == ("stem", YASNE_NEAR) and km < 15
    assert direction_anchor(GAZ, "Невідомому напрямку", ANCHORS) is None
    assert direction_anchor(GAZ, None, ANCHORS) is None


def test_resolve_refuses_a_place_too_far_from_its_direction():
    only_far = Gazetteer([POKROVSK, YASNE_FAR])
    near = direction_anchor(only_far, "Покровському напрямку", ANCHORS)
    how, found, km = resolve(only_far, "Ясного", near, max_km=120)
    assert how == "too_far" and found is None and km > 400


def test_paragraph_direction_is_found_anywhere_in_the_sentence():
    assert paragraph_direction("Атаки відбито на Лиманському напрямку , де") == (
        "Лиманському напрямку"
    )
    assert paragraph_direction("Слава Україні.") is None


def test_merge_adds_aliases_nearby_and_appends_the_rest():
    osm_same = place("osm:9", "Покровськ", 48.281, 37.181, "", aliases=["Красноармейск"])
    osm_new = place("osm:10", "Нове Село", 50.0, 30.0, "", aliases=[])
    out = merge([POKROVSK], [osm_same, osm_new])
    assert [p.gazetteer_id for p in out] == ["gn:1", "osm:10"]
    assert "Красноармейск" in out[0].aliases


def test_readers_and_table_round_trip(tmp_path):
    cols = "704422 Pokrovsk Pokrovsk Покровськ,Красноармійськ 48.28 37.18 P PPL UA".split()
    cols += ["", "05", "", "", "", "60127", "", "180", "Europe/Kyiv", "2026-01-01"]
    lake = [*cols[:6], "H", "LK", *cols[8:]]
    (tmp_path / "UA.txt").write_text("\t".join(cols) + "\n" + "\t".join(lake) + "\n", "utf-8")
    (tmp_path / "a.txt").write_text("UA.05\tDonetsk\tDonetsk\t709716\nRU.01\tX\tX\t1\n", "utf-8")
    admin = read_admin1(tmp_path / "a.txt")
    places = read_geonames(tmp_path / "UA.txt", admin)
    assert admin == {"05": "Donetsk"} and len(places) == 1
    assert places[0].oblast == "Donetsk" and "Покровськ" in places[0].aliases
    tags = {"place": "village", "name": "Ясне", "name:en": "Yasne"}
    osm = {"elements": [{"type": "node", "id": 7, "lat": 48.0, "lon": 37.0, "tags": tags}]}
    (tmp_path / "osm.json").write_text(json.dumps(osm), "utf-8")
    nodes = read_osm(tmp_path / "osm.json")
    assert nodes[0].gazetteer_id == "osm:7" and nodes[0].name == "Yasne"
    write_table(places + nodes, tmp_path / "g.parquet")
    assert read_table(tmp_path / "g.parquet") == places + nodes
