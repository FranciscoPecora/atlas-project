"""The one test-split run per release (SPEC 5.4). Called only by `make eval-test`.

    make eval-test                 # General Staff (eval/test_run.json)
    make eval-test SOURCE=af       # an A2 source (eval/test_run_af.json), once each

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
A2_SYSTEMS = ("B2", "S1", "S3-H")  # amendment A2: B0 and B1 are General Staff rules


class Refused(RuntimeError):
    pass


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=root,
                          check=True).stdout.strip()  # fmt: skip


def missing_runs(
    test_days: list[str], systems: tuple[str, ...], exists: Callable[[str, str], bool],
    source: str = "gsu",
) -> list[str]:  # fmt: skip
    """'<system> <report_id>' for each saved run that is not there."""
    rids = [f"{source}-{d}" for d in test_days]
    return [f"{s} {r}" for s in systems for r in rids if not exists(s, r)]


def marker_path(source: str) -> Path:
    """GSU keeps A1's marker; each A2 source has its own (amendment A2)."""
    return MARKER if source == "gsu" else MARKER.with_name(f"test_run_{source}.json")


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
    source: str = "gsu",
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
    systems = MODEL_SYSTEMS if source == "gsu" else A2_SYSTEMS
    gaps = missing_runs(test_days, systems, exists, source)
    if gaps:
        raise Refused(f"saved runs missing ({len(gaps)}): {', '.join(gaps[:8])}")
    before = count_rows(results)
    payload: dict[str, Any] = {
        "status": "started", "commit": commit, "config_hash": config_hash(cfg), "config": cfg,
        "source": source, "test_reports": [f"{source}-{d}" for d in test_days],
        "started": now().isoformat(),
    }  # fmt: skip
    write_marker(marker, payload)
    score()
    payload.update(status="finished", finished=now().isoformat(),
                   rows_appended=count_rows(results) - before)  # fmt: skip
    write_marker(marker, payload)
    return payload


def test_days_for(source: str, cfg: dict[str, Any]) -> list[str]:
    """Collected test-report dates of a source (GSU: SPEC 4.2; AF, RUMOD: amendment A2)."""
    from src.labels import SPEC
    from src.review import gsu_test_dates
    from src.sources import a2_units, text_path

    if source == "gsu":
        return gsu_test_dates(SPEC.read_text(encoding="utf-8"))[0]
    days = [d for d, split in a2_units(source, cfg) if split == "test"]
    return [d for d in days if text_path(source, d).exists()]


def main(argv: list[str] | None = None) -> None:
    import argparse

    from eval import score
    from src.config import load_config
    from src.extract import read_pred

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["gsu", "af", "rumod"], default="gsu")
    source = ap.parse_args(argv).source
    cfg = load_config()

    def scorer() -> None:
        os.environ["ATLAS_EVAL_TEST"] = "1"
        score.main(["--split", "test", "--source", source])

    marker = marker_path(source)
    out = run(
        scorer, json.loads(json.dumps(cfg, default=str)), test_days_for(source, cfg),
        lambda s, rid: read_pred(s, rid) is not None,
        commit=git("rev-parse", "HEAD"), dirty=bool(git("status", "--porcelain")),
        marker=marker, source=source,
    )  # fmt: skip
    print(f"test run finished: {out['rows_appended']} rows appended; {marker.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Refused as why:
        raise SystemExit(f"make eval-test refused: {why}") from None
