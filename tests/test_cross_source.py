from datetime import date

import polars as pl

from src import cross_source


def test_km_is_about_111_per_degree_of_latitude():
    assert abs(cross_source.km(48.0, 37.0, 49.0, 37.0) - 111.2) < 0.2


def test_compare_counts_assaults_before_and_after_a_claim():
    claims = [(date(2026, 8, 10), 48.0, 37.0), (date(2026, 8, 10), 50.0, 30.0)]
    assaults = [
        (date(2026, 8, 7), 48.01, 37.0),  # 1 km away, 3 days before
        (date(2026, 8, 20), 48.0, 37.01),  # after
        (date(2026, 8, 9), 48.5, 37.0),  # 55 km away: ignored
    ]
    out = cross_source.compare(claims, assaults)
    assert out == {"claims": 2, "assault_before": 1, "assault_after": 1,
                   "median_days_since_assault": 3}  # fmt: skip


def test_claims_and_assaults_keeps_located_rows_of_each_kind():
    ledger = pl.DataFrame({
        "source": ["rumod", "rumod", "gsu", "gsu"],
        "event_type": ["territorial_advance", "territorial_advance", "ground_assault", "shelling"],
        "event_date": ["2026-08-10"] * 4,
        "lat": [48.0, None, 48.0, 48.0], "lon": [37.0, None, 37.0, 37.0],
    })  # fmt: skip
    claims, assaults = cross_source.claims_and_assaults(ledger)
    assert claims == [(date(2026, 8, 10), 48.0, 37.0)] and len(assaults) == 1
