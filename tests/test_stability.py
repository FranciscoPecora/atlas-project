from src.stability import compare, kappa, loose_match, with_ids


def ev(kind, lat, status="ua_claimed"):
    return {
        "report_id": "gsu-2026-07-21",
        "sector": "FULL",
        "event_type": kind,
        "epistemic_status": status,
        "event_date": "2026-07-20",
        "lat": lat,
        "lon": 37.0,
    }


RUN1 = with_ids([ev("ground_assault", 48.0), ev("shelling", 49.0), ev("air_strike", 50.0)], "a")
RUN2 = with_ids([ev("ground_assault", 48.0), ev("ground_assault", 49.0)], "b")


def test_loose_match_pairs_by_place_so_a_changed_type_is_a_disagreement():
    pairs = loose_match(RUN1, RUN2)
    assert [(a["event_type"], b["event_type"]) for a, b in pairs] == [
        ("ground_assault", "ground_assault"),
        ("shelling", "ground_assault"),
    ]


def test_kappa_is_one_for_identical_runs_and_for_a_single_shared_value():
    same = loose_match(RUN1, with_ids(RUN1, "c"))
    assert kappa(same, "event_type") == 1.0
    assert kappa(same, "epistemic_status") == 1.0
    assert kappa([], "event_type") is None


def test_compare_reports_counts_and_a_lower_kappa_on_disagreement():
    res = compare(RUN1, RUN2)
    assert (res["first"], res["second"], res["matched"]) == (3, 2, 2)
    assert res["kappa_event_type"] < 1.0
