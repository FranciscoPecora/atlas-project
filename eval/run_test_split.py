"""The one test-split run per release (SPEC 5.4). Called only by `make eval-test`.

    make eval-test

Refuses to run if eval/test_run.json exists, or if the working tree has uncommitted
changes (the commit hash recorded must describe the code that ran). Before anything
is scored it checks that every model system has a saved run for every collected test
report, so a missing file cannot spend the run. Then it writes eval/test_run.json
with status "started", calls eval/score.py on the test split (the only code that
opens eval/gold/test/), and rewrites the file with status "finished", the rows
appended to eval/results.csv and the time. The marker is written before scoring:
a crash still counts as the run.

This module never opens eval/gold/test/ itself.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / "eval" / "test_run.json"
RESULTS = ROOT / "eval" / "results.csv"
MODEL_SYSTEMS = ("B2", "S1", "S3-H", "S3-S")  # B0, B1 and S2 are computed by the scorer


class Refused(RuntimeError):
    pass


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=root,
                          check=True).stdout.strip()  # fmt: skip


def missing_runs(
    test_days: list[str], systems: tuple[str, ...], exists: Callable[[str, str], bool]
) -> list[str]:
    """'<system> <report_id>' for each saved run that is not there."""
    return [f"{s} gsu-{d}" for s in systems for d in test_days if not exists(s, f"gsu-{d}")]


def count_rows(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def write_marker(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def run(
    score: Callable[[], None],
    cfg: dict[str, Any],
    test_days: list[str],
    exists: Callable[[str, str], bool],
    commit: str,
    dirty: bool,
    marker: Path = MARKER,
    results: Path = RESULTS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Check, mark, score once, mark finished. Returns the final marker contents."""
    from src.config import config_hash

    if marker.exists():
        raise Refused(
            f"{marker.name} exists: the test split was already scored for this release. "
            "Delete it only for a new release, and say so in DECISIONS.md."
        )
    if dirty:
        raise Refused("uncommitted changes: commit first, so the recorded hash is the code run")
    if not test_days:
        raise Refused("no collected test report")
    gaps = missing_runs(test_days, MODEL_SYSTEMS, exists)
    if gaps:
        raise Refused(f"saved runs missing ({len(gaps)}): {', '.join(gaps[:8])}")
    before = count_rows(results)
    payload: dict[str, Any] = {
        "status": "started", "commit": commit, "config_hash": config_hash(cfg), "config": cfg,
        "test_reports": [f"gsu-{d}" for d in test_days], "started": now().isoformat(),
    }  # fmt: skip
    write_marker(marker, payload)
    score()
    payload.update(status="finished", finished=now().isoformat(),
                   rows_appended=count_rows(results) - before)  # fmt: skip
    write_marker(marker, payload)
    return payload


def main() -> None:
    from eval import score
    from src.config import load_config
    from src.extract import read_pred
    from src.labels import SPEC
    from src.review import gsu_test_dates

    cfg = load_config()
    test_days, _ = gsu_test_dates(SPEC.read_text(encoding="utf-8"))

    def scorer() -> None:
        os.environ["CLAIMLINE_EVAL_TEST"] = "1"
        score.main(["--split", "test"])

    out = run(
        scorer, json.loads(json.dumps(cfg, default=str)), test_days,
        lambda s, rid: read_pred(s, rid) is not None,
        commit=git("rev-parse", "HEAD"), dirty=bool(git("status", "--porcelain")),
    )  # fmt: skip
    print(f"test run finished: {out['rows_appended']} rows appended; {MARKER.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Refused as why:
        raise SystemExit(f"make eval-test refused: {why}") from None
