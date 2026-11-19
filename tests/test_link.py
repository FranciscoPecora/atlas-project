import polars as pl
import pytest

from eval.score import haversine_km
from src import link

CFG = {
    "corpus": {"start": "2026-07-19", "analysis_end": "2026-10-16"},
    "link": {"duplicate_km": 5, "duplicate_days": 3, "confirmation_days": 30},
}


def ev(eid, etype="ground_assault", date="2026-08-01", lat=48.0, lon=37.0, **kw) -> dict:
    row = {
        "event_id": eid, "report_id": kw.pop("report_id", f"r-{eid}"), "event_type": etype,
        "event_date": date, "report_date": kw.pop("report_date", date), "lat": lat, "lon": lon,
        "sector": "FULL", "actor": "RU", "epistemic_status": "ua_claimed",
        "geo_precision": 1, "gazetteer_id": "gn:1",
    }  # fmt: skip
    row.update(kw)
    return row


def frame(rows):
    return pl.DataFrame(rows, infer_schema_length=None)


# 0.03 degrees of latitude is about 3.3 km; 0.06 about 6.7 km.


def test_haversine_sql_matches_python():
    import duckdb

    sql = f"select {link.haversine_sql('a', 'b')} from (select 48.0 lat, 37.0 lon) a, "
    sql += "(select 48.5 lat, 37.6 lon) b"
    got = duckdb.sql(sql).fetchall()[0][0]
    assert got == pytest.approx(haversine_km(48.0, 37.0, 48.5, 37.6), rel=1e-9)


def test_edges_need_type_distance_and_days():
    rows = [
        ev("a"),
        ev("b", lat=48.03),  # 3.3 km, same day: linked
        ev("c", lat=48.06),  # 6.7 km from a, 3.3 km from b: linked to b only
        ev("d", etype="shelling"),  # other type
        ev("e", date="2026-08-05"),  # 4 days later
        ev("f", date="2026-08-04"),  # 3 days later: linked to a and b
        ev("g", lat=None, lon=None),  # no coordinates
    ]
    edges = link.duplicate_edges(frame(rows), km=5, days=3)
    assert ("a", "b") in edges and ("b", "c") in edges and ("a", "f") in edges
    assert ("a", "c") not in edges
    assert not any("d" in e or "g" in e for e in edges)
    assert ("a", "e") not in edges and ("e", "f") in edges  # 1 day apart


def test_components_chain_and_singletons():
    got = link.components(["c", "a", "b", "x"], [("b", "c"), ("a", "b")])
    assert got["a"] == got["b"] == got["c"] == 0  # chained through b
    assert got["x"] == 1


def test_components_numbering_ignores_edge_order():
    ids = ["a", "b", "c", "d"]
    one = link.components(ids, [("c", "d"), ("a", "b")])
    two = link.components(ids, [("a", "b"), ("c", "d")])
    assert one == two == {"a": 0, "b": 0, "c": 1, "d": 1}


def test_cluster_diameter_reports_chaining():
    rows = [ev("a"), ev("b", lat=48.03), ev("c", lat=48.06), ev("z", lat=50.0)]
    led = frame(rows)
    clusters = link.cluster_table(led, 5, 3)
    diam = link.cluster_diameters(led, clusters)
    assert diam.height == 1 and diam["size"][0] == 3
    assert diam["diameter_km"][0] == pytest.approx(haversine_km(48.0, 37.0, 48.06, 37.0))
    assert diam["diameter_km"][0] > 5  # the chain is wider than the link distance


def claim(eid, rd, **kw):
    base = {"event_type": "territorial_advance", "epistemic_status": "ru_claimed"}
    return ev(eid, report_date=rd, date=rd, **{**base, **kw})


def confirm(eid, rd, **kw):
    return claim(eid, rd, epistemic_status="geolocated_confirmed", **kw)


def test_confirmation_earliest_report_wins():
    rows = [
        claim("c1", "2026-08-01"),
        confirm("k2", "2026-08-20"),
        confirm("k1", "2026-08-10"),
    ]
    links, excluded = link.confirmation_links(frame(rows), "2026-07-19", "2026-10-16", 30)
    (row,) = links.to_dicts()
    assert row["claim_id"] == "c1" and row["confirm_id"] == "k1" and row["lag_days"] == 9
    assert excluded == 0


def test_confirmation_rules_place_actor_window():
    rows = [
        claim("c1", "2026-08-01"),
        confirm("k_place", "2026-08-02", gazetteer_id="gn:2"),
        confirm("k_actor", "2026-08-02", actor="UA"),
        confirm("k_before", "2026-07-31"),
        confirm("k_late", "2026-09-01"),  # 31 days
        claim("c2", "2026-09-10"),
        confirm("k_edge", "2026-10-10"),  # exactly 30 days after c2
        confirm("k_same", "2026-09-10", report_id="r-other"),  # same day as c2
    ]
    links, _ = link.confirmation_links(frame(rows), "2026-07-19", "2026-10-16", 30)
    got = {r["claim_id"]: (r["confirm_id"], r["lag_days"]) for r in links.to_dicts()}
    assert got["c1"] == (None, None)
    assert got["c2"] == ("k_same", 0)


def test_confirmation_claim_filters_and_exclusions():
    rows = [
        claim("in_window", "2026-10-16"),
        claim("after_window", "2026-10-17"),  # observation-only window: not a claim
        claim("ua", "2026-08-01", epistemic_status="ua_claimed", actor="UA"),
        claim("analyst", "2026-08-01", epistemic_status="analyst_assessed"),
        claim("assault", "2026-08-01", event_type="ground_assault"),
        claim("vague", "2026-08-01", geo_precision=2),
        claim("no_prec", "2026-08-01", geo_precision=None),
    ]
    links, excluded = link.confirmation_links(frame(rows), "2026-07-19", "2026-10-16", 30)
    assert sorted(links["claim_id"].to_list()) == ["in_window", "ua"]
    assert excluded == 2


def test_run_on_a_ledger_with_no_claims():
    out = link.run(frame([ev("a"), ev("b", lat=48.03)]), CFG)
    assert out["confirmations"].height == 0 and out["excluded_precision"] == 0
    assert out["n_clusters_multi"] == 1 and out["clusters"]["cluster_size"].to_list() == [2, 2]
