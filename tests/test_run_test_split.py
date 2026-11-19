"""eval/test_run.py with a fake scorer: nothing here opens eval/gold/test/."""

import json
from datetime import UTC, datetime

import pytest

from eval import run_test_split as test_run

CFG = {"eval": {"seed": 1}}
DAYS = ["2026-08-25", "2026-08-31"]


def fake_scorer(results, rows=3):
    calls = []

    def score():
        calls.append(1)
        with results.open("a", encoding="utf-8") as f:
            f.write("row\n" * rows)

    return score, calls


def go(tmp_path, **kw):
    results = tmp_path / "results.csv"
    results.write_text("header\n", encoding="utf-8")
    score, calls = fake_scorer(results)
    args = {
        "score": score, "cfg": CFG, "test_days": DAYS, "exists": lambda s, r: True,
        "commit": "abc123", "dirty": False, "marker": tmp_path / "test_run.json",
        "results": results, "now": lambda: datetime(2026, 12, 20, tzinfo=UTC),
    }  # fmt: skip
    args.update(kw)
    return test_run.run(**args), calls, args["marker"]


def test_runs_once_and_records_everything(tmp_path):
    out, calls, marker = go(tmp_path)
    assert calls == [1]
    saved = json.loads(marker.read_text())
    assert saved == out
    assert saved["status"] == "finished" and saved["commit"] == "abc123"
    assert saved["rows_appended"] == 3 and saved["config"] == CFG
    assert len(saved["config_hash"]) == 12
    assert saved["test_reports"] == ["gsu-2026-08-25", "gsu-2026-08-31"]
    assert saved["started"].startswith("2026-12-20")


def test_refuses_when_marker_exists(tmp_path):
    (tmp_path / "test_run.json").write_text("{}")
    with pytest.raises(test_run.Refused, match="already scored"):
        go(tmp_path)


def test_second_run_is_refused(tmp_path):
    go(tmp_path)
    with pytest.raises(test_run.Refused):
        go(tmp_path)


def test_refuses_dirty_tree_before_scoring(tmp_path):
    with pytest.raises(test_run.Refused, match="uncommitted"):
        go(tmp_path, dirty=True)
    assert not (tmp_path / "test_run.json").exists()


def test_refuses_missing_runs_before_marking(tmp_path):
    with pytest.raises(test_run.Refused, match="S3-S gsu-2026-08-31"):
        go(tmp_path, exists=lambda s, r: not (s == "S3-S" and r == "gsu-2026-08-31"))
    assert not (tmp_path / "test_run.json").exists()


def test_crash_while_scoring_still_counts(tmp_path):
    def boom():
        raise RuntimeError("scorer crashed")

    with pytest.raises(RuntimeError):
        go(tmp_path, score=boom)
    saved = json.loads((tmp_path / "test_run.json").read_text())
    assert saved["status"] == "started"
    with pytest.raises(test_run.Refused):
        go(tmp_path)


def test_missing_runs_lists_each_gap():
    got = test_run.missing_runs(["d1", "d2"], ("S1", "B2"), lambda s, r: r != "gsu-d2")
    assert got == ["S1 gsu-d2", "B2 gsu-d2"]


def test_a2_sources_have_their_own_marker_and_systems():
    from eval import run_test_split as r

    assert r.marker_path("gsu").name == "test_run.json"
    assert r.marker_path("af").name == "test_run_af.json"
    gaps = r.missing_runs(["2026-08-14"], r.A2_SYSTEMS, lambda s, rid: s == "S1", "rumod")
    assert gaps == ["B2 rumod-2026-08-14", "S3-H rumod-2026-08-14"]
