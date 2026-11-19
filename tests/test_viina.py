import hashlib
import io
import zipfile
from types import SimpleNamespace as NS

import polars as pl
import pytest

from src import viina

NAMES = {"Donets'k": "Donetsk", "Kharkiv": "Kharkiv"}


def zipped_csv(path, rows):
    header = "date,ADM1_NAME,t_mil_b\n"
    body = "".join(f"{d},{o},{m}\n" for d, o, m in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("event_1pd_latest_2026.csv", header + body)
    path.write_bytes(buf.getvalue())
    return path


def test_read_viina_maps_oblasts_and_dates(tmp_path):
    p = zipped_csv(tmp_path / "v.zip", [("20260801", "Donets'k", 1), ("20260802", "Kharkiv", 0),
                                         ("20260803", "", 1)])  # fmt: skip
    got = viina.read_viina(p, NAMES)
    assert got.to_dicts() == [
        {"event_date": "2026-08-01", "oblast": "Donetsk", "t_mil": True},
        {"event_date": "2026-08-02", "oblast": "Kharkiv", "t_mil": False},
    ]


def test_read_viina_refuses_unmapped_oblasts(tmp_path):
    p = zipped_csv(tmp_path / "v.zip", [("20260801", "Atlantis", 1)])
    with pytest.raises(ValueError, match="Atlantis"):
        viina.read_viina(p, NAMES)


def test_covered_days_shift_back_one_day():
    got = viina.covered_days(["2026-07-19", "2026-07-21", "2026-11-17"], "2026-07-19",
                             "2026-11-15")  # fmt: skip
    assert got == ["2026-07-20"]  # 07-18 is before the window, 11-16 after


def test_ledger_events_need_an_oblast():
    led = pl.DataFrame({"event_date": ["2026-08-01"] * 3, "gazetteer_id": ["g1", "g2", None]})
    got = viina.ledger_events(led, {"g1": "Donetsk"})
    assert got.to_dicts() == [{"event_date": "2026-08-01", "oblast": "Donetsk"}]


def test_grid_fills_zeros_and_keeps_active_oblasts():
    a = pl.DataFrame({"event_date": ["d1"], "oblast": ["Donetsk"], "n": [3]}).cast({"n": pl.UInt32})
    b = pl.DataFrame({"event_date": ["d2"], "oblast": ["Kharkiv"], "n": [2]}).cast({"n": pl.UInt32})
    grid = viina.oblast_day_grid(a, b, ["d1", "d2"])
    assert grid.height == 4  # 2 days x 2 oblasts
    assert grid.filter(pl.col("oblast") == "Donetsk")["n_a"].to_list() == [3, 0]
    assert grid["n_b"].sum() == 2


def test_spearman_uses_ranks_and_handles_constants():
    grid = pl.DataFrame({"n_a": [1, 2, 3, 4], "n_b": [1, 4, 9, 100]})
    assert viina.spearman(grid) == pytest.approx(1.0)  # monotone, not linear
    assert viina.spearman(pl.DataFrame({"n_a": [0, 0], "n_b": [1, 2]})) is None


def test_compare_end_to_end():
    ledger = pl.DataFrame({"event_date": ["2026-08-01", "2026-08-01", "2026-08-02"],
                           "gazetteer_id": ["g1", "g1", "g2"]})  # fmt: skip
    vi = pl.DataFrame({"event_date": ["2026-08-01", "2026-08-02", "2026-08-02"],
                       "oblast": ["Donetsk", "Kharkiv", "Kharkiv"],
                       "t_mil": [True, True, False]})  # fmt: skip
    res = viina.compare(ledger, vi, {"g1": "Donetsk", "g2": "Kharkiv"},
                        ["2026-08-01", "2026-08-02"])  # fmt: skip
    assert res["ledger_events"] == 3
    assert res["all"]["oblast_days"] == 4 and res["all"]["viina_events"] == 3
    assert res["t_mil"]["viina_events"] == 2


def test_fetch_checks_the_pinned_hash(tmp_path):
    data = b"zip bytes"
    oid = hashlib.sha256(data).hexdigest()
    cfg = {"viina": {"repo": "o/r", "file": "f.zip", "oid": oid, "size": len(data)},
           "collect": {"timeout_seconds": 1, "user_agent": "x"}}  # fmt: skip
    calls = []

    class Http:
        def post(self, url, json, headers):
            calls.append(url)
            href = {"objects": [{"actions": {"download": {"href": "https://dl"}}}]}
            return NS(raise_for_status=lambda: None, json=lambda: href)

        def get(self, url):
            return NS(content=data)

    path = viina.fetch(cfg, tmp_path, Http())
    assert path.read_bytes() == data and calls == [
        "https://github.com/o/r.git/info/lfs/objects/batch"
    ]
    assert viina.fetch(cfg, tmp_path, None) == path  # cached: no second download
    cfg["viina"]["oid"] = "0" * 64
    (tmp_path / "f.zip").unlink()
    with pytest.raises(RuntimeError, match="SHA-256"):
        viina.fetch(cfg, tmp_path, Http())
