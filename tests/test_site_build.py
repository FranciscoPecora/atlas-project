import json
from datetime import UTC, date, datetime

import polars as pl

from src import site_build

BUILT = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)


def row(i: int, report: str, event: str, lat: float | None = 48.0) -> dict:
    return {
        "event_id": f"e{i}", "report_id": f"gsu-{report}", "source": "gsu",
        "report_date": date.fromisoformat(report), "event_date": date.fromisoformat(event),
        "event_type": "shelling", "epistemic_status": "ua_claimed", "actor": "RU",
        "target": None, "geo_precision": 1, "quantity": None, "gazetteer_id": "gn:1",
        "place_name": "Yasne", "oblast": "Donetsk", "lat": lat, "lon": 37.123456,
        "cluster_id": i, "cluster_size": 1, "confirmed_by": None, "lag_days": None,
        "evidence_start": 3, "evidence_end": 9, "text_sha256": "b" * 64,
        "source_url": "https://u", "system": "S3-H", "run_id": "r",
    }  # fmt: skip


def test_cutoff_date_needs_the_whole_day_to_end_48_hours_before():
    # 19 Nov 20:00 minus 48 h is 17 Nov 20:00; 17 Nov ends after that, 16 Nov before it.
    assert site_build.cutoff_date(BUILT, 48) == date(2026, 11, 16)
    assert site_build.cutoff_date(datetime(2026, 11, 19, 0, 0, tzinfo=UTC), 48) == date(
        2026, 11, 16
    )


def test_apply_delay_drops_recent_report_or_event_dates():
    frame = pl.DataFrame([row(0, "2026-11-16", "2026-11-15"), row(1, "2026-11-17", "2026-11-16"),
                          row(2, "2026-11-16", "2026-11-17")])  # fmt: skip
    kept = site_build.apply_delay(frame, BUILT, 48)
    assert kept["event_id"].to_list() == ["e0"]


def test_geojson_keeps_located_events_with_short_properties():
    frame = pl.DataFrame([row(0, "2026-08-02", "2026-08-01"),
                          row(1, "2026-08-02", "2026-08-01", lat=None)])  # fmt: skip
    gj = site_build.geojson(frame)
    (f,) = gj["features"]
    assert f["geometry"]["coordinates"] == [37.1235, 48.0]
    assert f["properties"]["t"] == "shelling" and f["properties"]["es"] == 3
    assert f["properties"]["x"] == "gsu"
    assert "h" not in f["properties"]  # the hash stays in the release file
    assert "evidence_quote" not in f["properties"]


def test_split_scores_reads_test_rows_only(tmp_path):
    path = tmp_path / "results.csv"
    path.write_text(
        "commit,config_hash,date,split,system,metric,value,n,config\n"
        "a,b,2026-11-19,test,S3-H,event_f1,0.89,621,x\n"
        "a,b,2026-11-19,dev,S3-H,event_f1,0.92,175,x\n"
        "a,b,2026-11-19,test,S3-H,event_recall,0.85,621,x\n"
    )
    assert site_build.split_scores(path) == {"S3-H": {"event_f1": 0.89}}
    assert site_build.split_scores(tmp_path / "missing.csv") == {}


def test_build_writes_geojson_and_meta(tmp_path):
    public = tmp_path / "pub.parquet"
    pl.DataFrame([row(0, "2026-08-02", "2026-08-01"),
                  row(1, "2026-11-18", "2026-11-17")]).write_parquet(public)  # fmt: skip
    info = site_build.build(BUILT, tmp_path / "out", public)
    assert info["n_events"] == 1 and info["n_withheld_delay"] == 1 and info["n_pairs"] == 0
    assert info["last_report"] == "2026-08-02" and info["delay_hours"] == 48
    saved = json.loads((tmp_path / "out" / "meta.json").read_text())
    assert saved["cutoff_date"] == "2026-11-16"
    gj = json.loads((tmp_path / "out" / "events.geojson").read_text())
    assert len(gj["features"]) == 1
