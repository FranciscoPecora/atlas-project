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


def test_fact_rows_convert_cost_and_list_rejections():
    from eval.score import fact_rows

    facts = {"S2": {"cost_usd_per_report": 0.01, "seconds_median": 50.0,
                    "rejected": {"quote_missing": 2}, "n_before": 40}}  # fmt: skip
    rows = {r["metric"]: r for r in fact_rows(facts, 0.9, "dev")}
    assert rows["cost_eur_per_report"]["value"] == 0.009
    assert rows["rejected_quote_missing"]["value"] == 2
    assert rows["rejected_quote_missing"]["n"] == 40


def test_metric_rows_score_only_the_gold_given():
    from eval.score import metric_rows

    ev = {"match_km": 10, "match_days": 1, "bootstrap_resamples": 10, "seed": 1,
          "grid_km": [10], "grid_days": [1]}  # fmt: skip
    base = {"sector": "FULL", "event_type": "shelling", "event_date": "2026-07-20",
            "lat": None, "lon": None}  # fmt: skip
    gold = [{**base, "id": "g1", "report_id": "r1"}]
    preds = {
        "X": [{**base, "id": "p1", "report_id": "r1"}, {**base, "id": "p2", "report_id": "r2"}]
    }
    rows = {r["metric"]: r["value"] for r in metric_rows(preds, gold, ev, "dev-heldout")}
    assert rows["event_f1"] == 1.0  # the prediction for r2 is outside the gold units


def test_geocode_tolerates_a_record_without_offsets():
    from src.geocode import paragraph_at

    assert paragraph_at("One.\n\nTwo.", None) == ""
