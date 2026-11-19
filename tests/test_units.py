import json

from src.units import (
    approved,
    best_alias,
    extracted_names,
    new_id,
    normalise,
    numbers,
    proposals,
    resolve,
    unit_ids,
)

# Invented alias table.
TABLE = [
    {"unit_id": "u:3-assault", "alias": "3rd Separate Assault Brigade", "added": "2026-11-19"},
    {"unit_id": "u:3-assault", "alias": "3-я окрема штурмова бригада", "added": "2026-11-19"},
    {"unit_id": "u:47-mech", "alias": "47th Mechanized Brigade", "added": "2026-11-19"},
]


def test_normalise_strips_ordinals_case_and_punctuation():
    assert normalise("3rd Separate Assault Brigade (OShBr)") == "3 separate assault brigade oshbr"
    assert normalise("3-я окрема штурмова бригада") == "3 окрема штурмова бригада"
    assert numbers("the 3rd and 47th") == ("3", "47")


def test_resolve_exact_then_fuzzy():
    assert resolve("3rd separate assault brigade", TABLE, 85) == "u:3-assault"
    assert resolve("3rd Assault Brigade", TABLE, 85) == "u:3-assault"  # token set match
    assert resolve("3-я окрема штурмова бригада", TABLE, 85) == "u:3-assault"


def test_different_numbers_never_match():
    assert resolve("47th Separate Assault Brigade", TABLE, 85) is None
    row, _ = best_alias("4th Mechanized Brigade", TABLE)
    assert row is None


def test_unit_ids_keep_order_and_drop_repeats_and_misses():
    units = [{"name": "47th Mechanized Brigade"}, {"name": "3rd Assault Brigade"},
             {"name": "47th mechanized brigade"}, {"name": "Unknown 99th Regiment"}]  # fmt: skip
    assert unit_ids(units, TABLE, 85) == ["u:47-mech", "u:3-assault"]


def test_new_id_is_readable_and_unique():
    assert new_id("1st Tank Brigade", set()) == "u:1-tank-brigade"
    assert new_id("1st Tank Brigade", {"u:1-tank-brigade"}) == "u:1-tank-brigade-2"


def test_proposals_suggest_a_near_unit_or_a_new_id_and_skip_resolved_names():
    names = {"3rd Assault Brigade": 4, "47th Mech. Bde": 2, "1st Tank Brigade": 1}
    rows = proposals(names, TABLE, 85)
    assert [r["name"] for r in rows] == ["47th Mech. Bde", "1st Tank Brigade"]
    assert rows[0]["unit_id"] == "u:47-mech" and rows[0]["approve"] == ""
    assert rows[1]["unit_id"] == "u:1-tank-brigade"


def test_only_rows_marked_y_are_approved():
    review = [{"name": "a", "unit_id": "u:a", "approve": "Y"},
              {"name": "b", "unit_id": "u:b", "approve": ""},
              {"name": "c", "unit_id": " ", "approve": "y"}]  # fmt: skip
    assert approved(review, "2026-11-19") == [
        {"unit_id": "u:a", "alias": "a", "added": "2026-11-19"}
    ]


def test_extracted_names_counts_units_in_saved_runs(tmp_path):
    folder = tmp_path / "S1"
    folder.mkdir()
    events = [{"units": [{"name": "X Brigade"}]}, {"units": [{"name": "X Brigade"}]}, {"units": []}]
    (folder / "r.json").write_text(json.dumps({"events": events}))
    assert extracted_names("S1", tmp_path) == {"X Brigade": 2}
