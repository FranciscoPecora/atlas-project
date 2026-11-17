"""Five hand-made cases for SPEC.md 5.1, plus the interval and the grid.

All events sit on one meridian. One degree of latitude is 111.2 km, so
0.05 degrees is about 5.6 km and 0.108 degrees is about 12 km.
"""

import pytest

from eval.score import bootstrap_f1, counts_by_report, grid, haversine_km, match, score


def ev(id_, lat=48.0, day="2026-08-05", kind="ground_assault", report="gsu-2026-08-06", **kw):
    base = {
        "id": id_,
        "report_id": report,
        "sector": "FULL",
        "event_type": kind,
        "event_date": day,
        "lat": lat,
        "lon": 37.0,
    }
    return {**base, **kw}


GOLD = [ev("g1")]


def test_haversine_one_degree_of_latitude():
    assert haversine_km(48.0, 37.0, 49.0, 37.0) == pytest.approx(111.2, abs=0.1)


def test_1_perfect_match():
    res = score([ev("p1")], GOLD, resamples=50)
    assert (res["tp"], res["fp"], res["fn"], res["f1"]) == (1, 0, 0, 1.0)


def test_2_a_12_km_miss_does_not_match_at_10_km():
    far = ev("p1", lat=48.108)
    assert haversine_km(48.0, 37.0, 48.108, 37.0) == pytest.approx(12.0, abs=0.1)
    res = score([far], GOLD, resamples=50)
    assert (res["tp"], res["fp"], res["fn"], res["f1"]) == (0, 1, 1, 0.0)
    assert score([far], GOLD, k_km=25, resamples=50)["tp"] == 1


def test_3_a_2_day_miss_does_not_match_at_1_day():
    late = ev("p1", day="2026-08-07")
    assert score([late], GOLD, resamples=50)["tp"] == 0
    assert score([late], GOLD, d_days=2, resamples=50)["tp"] == 1
    assert score([ev("p1", day="2026-08-06")], GOLD, resamples=50)["tp"] == 1


def test_4_two_predictions_for_one_gold_event_give_one_match_and_one_false_positive():
    near, nearer = ev("p1", lat=48.05), ev("p2", lat=48.01)
    res = score([near, nearer], GOLD, resamples=50)
    assert (res["tp"], res["fp"], res["fn"]) == (1, 1, 0)
    assert res["precision"] == 0.5 and res["recall"] == 1.0
    assert match([near, nearer], GOLD)[0][0]["id"] == "p2"  # the closest pair wins


def test_5_a_type_mismatch_does_not_match():
    res = score([ev("p1", kind="shelling")], GOLD, resamples=50)
    assert (res["tp"], res["fp"], res["fn"]) == (0, 1, 1)


def test_location_rule_both_null_pass_one_null_fail():
    no_place = ev("g1", lat=None, lon=None)
    assert score([ev("p1", lat=None, lon=None)], [no_place], resamples=50)["tp"] == 1
    assert score([ev("p1")], [no_place], resamples=50)["tp"] == 0


def test_other_reports_sectors_and_non_gold_units_never_match():
    assert score([ev("p1", sector="DONETSK")], GOLD, resamples=50)["tp"] == 0
    res = score([ev("p1"), ev("p2", report="gsu-2026-09-01")], GOLD, resamples=50)
    assert (res["tp"], res["fp"]) == (1, 0)  # the prediction outside gold units is discarded


def test_bootstrap_resamples_whole_reports_and_is_seeded():
    per_report = {"a": (1, 1, 1), "b": (0, 1, 1)}
    low, high = bootstrap_f1(per_report, resamples=200, seed=1)
    assert (low, high) == (0.0, 1.0)
    assert bootstrap_f1(per_report, resamples=200, seed=1) == (low, high)
    assert bootstrap_f1({"a": (2, 2, 2)}, resamples=50) == (1.0, 1.0)


def test_counts_by_report_and_grid():
    gold = [ev("g1"), ev("g2", report="gsu-2026-07-29", day="2026-07-28")]
    preds = [ev("p1", lat=48.108), ev("p2", report="gsu-2026-07-29", day="2026-07-28")]
    assert counts_by_report(preds, gold) == {
        "gsu-2026-07-29": (1, 1, 1),
        "gsu-2026-08-06": (0, 1, 1),
    }
    cells = grid(preds, gold, [5, 10, 25], [0, 1, 2])
    assert cells[(10, 1)] == 0.5 and cells[(25, 0)] == 1.0 and len(cells) == 9
