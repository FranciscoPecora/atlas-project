import polars as pl
import pytest

from src import h2


def c(rid, lag, sector="DONETSK", status="ru_claimed", actor="RU"):
    return {"report_id": rid, "lag_days": lag, "sector": sector, "epistemic_status": status,
            "actor": actor}  # fmt: skip


def test_h2_claims_keeps_russian_claims_only():
    links = pl.DataFrame([c("a", 1), c("b", 2, status="ua_claimed", actor="UA"),
                          c("d", 3, actor="UA")])  # fmt: skip
    assert [r["report_id"] for r in h2.h2_claims(links)] == ["a"]


def test_confirmed_share_counts_lag_up_to_window():
    claims = [c("a", 0), c("a", 7), c("b", 8), c("b", None)]
    assert h2.confirmed_share(claims, 7) == 0.5
    assert h2.confirmed_share(claims, 30) == 0.75
    assert h2.confirmed_share([], 7) is None


def test_median_lag_over_confirmed_only():
    assert h2.median_lag([c("a", 2), c("a", None), c("b", 10)]) == 6.0
    assert h2.median_lag([c("a", None)]) is None


def test_bootstrap_resamples_whole_reports():
    # Report a: two confirmed claims; report b: two unconfirmed. Any resample holds an
    # even number of claims from each, so the share is always 0, 0.5 or 1.
    rows = [c("a", 1), c("a", 1), c("b", None), c("b", None)]
    seen = set()

    def stat(rs):
        seen.add(h2.confirmed_share(rs, 7))
        return h2.confirmed_share(rs, 7)

    low, high = h2.bootstrap(rows, stat, resamples=200, seed=1)
    assert seen <= {0.0, 0.5, 1.0}
    assert low == 0.0 and high == 1.0


def test_bootstrap_is_seeded_and_handles_empty():
    rows = [c(str(i), i if i % 3 else None) for i in range(30)]
    first = h2.bootstrap(rows, h2.median_lag, resamples=300, seed=5)
    assert first == h2.bootstrap(rows, h2.median_lag, resamples=300, seed=5)
    assert h2.bootstrap([], h2.median_lag) == (None, None)
    assert h2.bootstrap([c("a", None)], h2.median_lag, resamples=10) == (None, None)


def test_h2_numbers_and_verdict():
    links = pl.DataFrame([c("a", 3), c("b", 20), c("c", None), c("d", 5, sector="SOUTH")])
    res = h2.h2(links, [7, 14, 30], resamples=200, seed=1)
    assert res["n_claims"] == 4 and res["n_reports"] == 4 and res["n_confirmed_any"] == 3
    assert res["shares"][7]["share"] == 0.5 and res["shares"][30]["share"] == 0.75
    assert res["lags"]["DONETSK"]["median"] == 11.5 and res["lags"]["SOUTH"]["median"] == 5
    assert res["holds"] is False  # 14-day share 0.5 is not below 0.50


def test_h2_with_no_claims_is_undefined():
    empty = pl.DataFrame(schema={"report_id": pl.String, "lag_days": pl.Int64,
                                 "sector": pl.String, "epistemic_status": pl.String,
                                 "actor": pl.String})  # fmt: skip
    res = h2.h2(empty, [7, 14, 30], resamples=10, seed=1)
    assert res["n_claims"] == 0 and res["holds"] is None
    assert res["shares"][14] == {"share": None, "low": None, "high": None}
    text = h2.describe(res, excluded=0)
    assert "undefined (no eligible claim)" in text
    rows = h2.result_rows(res, 0)
    assert {"metric": "h2_confirmed_14d", "value": "", "n": 0} in rows


def test_result_rows_carry_intervals():
    links = pl.DataFrame([c("a", 3), c("b", None)])
    res = h2.h2(links, [14], resamples=50, seed=1)
    metrics = [r["metric"] for r in h2.result_rows(res, 2)]
    assert metrics[:2] == ["h2_claims", "h2_excluded_geo_precision"]
    assert {"h2_confirmed_14d", "h2_confirmed_14d_low", "h2_confirmed_14d_high"} <= set(metrics)
    assert "h2_median_lag_DONETSK" in metrics


def test_compute_runs_rule_7b_on_a_ledger():
    cfg = {"corpus": {"start": "2026-07-19", "analysis_end": "2026-10-16"},
           "link": {"confirmation_days": 30, "report_windows_days": [7, 14, 30]},
           "eval": {"bootstrap_resamples": 50, "seed": 1}}  # fmt: skip
    base = {"event_type": "territorial_advance", "actor": "RU", "geo_precision": 1,
            "gazetteer_id": "gn:1", "sector": "DONETSK"}  # fmt: skip
    ledger = pl.DataFrame([
        {**base, "event_id": "c", "report_id": "r1", "report_date": "2026-08-01",
         "epistemic_status": "ru_claimed"},
        {**base, "event_id": "k", "report_id": "r2", "report_date": "2026-08-11",
         "epistemic_status": "geolocated_confirmed"},
    ])  # fmt: skip
    res, excluded = h2.compute(ledger, cfg)
    assert res["n_claims"] == 1 and excluded == 0
    assert res["shares"][7]["share"] == 0 and res["shares"][14]["share"] == 1
    assert res["lags"]["DONETSK"]["median"] == pytest.approx(10)
