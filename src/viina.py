"""External validity: ledger event counts against VIINA, by oblast and day (SPEC 5.3).

    uv run python -m src.viina          # fetch VIINA if needed, print and log the correlation

VIINA 2.0 (Zhukov and Ayers, Harvard; Open Database License) geocodes and classifies
news reports about the war. The file used is VIINA's one-event-per-place-per-day
table for 2026, pinned in config.yaml to one Git LFS object, so a re-run reads the
same bytes. It is downloaded through GitHub's LFS batch endpoint (the repository
holds only a pointer) into data/raw/viina/ (git-ignored) and checked against its
SHA-256. Only the correlation is published, not VIINA rows.

The statistic is the Spearman rank correlation of daily event counts over
oblast-days. Days: the event dates the collected reports cover (a General Staff
report covers the day before its date; SPEC section 1), inside the corpus window.
Oblasts: those with at least one event in either dataset on those days. Missing
oblast-days count as zero. Ledger events without coordinates have no oblast and are
left out. Reported for VIINA's military-operations events (t_mil_b = 1) and for all
VIINA events.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from src.collect import DATA
from src.config import load_config

RAW = DATA / "raw" / "viina"
LFS_BATCH = "https://github.com/{repo}.git/info/lfs/objects/batch"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(cfg: dict[str, Any], folder: Path = RAW, http: Any = None) -> Path:
    """The pinned VIINA file, downloaded once and checked against its SHA-256 (the LFS oid)."""
    v = cfg["viina"]
    path = folder / v["file"]
    if path.exists() and sha256(path) == v["oid"]:
        return path
    import httpx

    http = http or httpx.Client(timeout=cfg["collect"]["timeout_seconds"],
                                headers={"User-Agent": cfg["collect"]["user_agent"]})  # fmt: skip
    headers = {"Accept": "application/vnd.git-lfs+json",
               "Content-Type": "application/vnd.git-lfs+json"}  # fmt: skip
    body = {"operation": "download", "transfers": ["basic"],
            "objects": [{"oid": v["oid"], "size": v["size"]}]}  # fmt: skip
    answer = http.post(LFS_BATCH.format(repo=v["repo"]), json=body, headers=headers)
    answer.raise_for_status()
    obj = answer.json()["objects"][0]
    if "error" in obj:
        raise RuntimeError(f"VIINA LFS object unavailable: {obj['error']}")
    data = http.get(obj["actions"]["download"]["href"]).content
    if hashlib.sha256(data).hexdigest() != v["oid"]:
        raise RuntimeError("VIINA download does not match the pinned SHA-256")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def read_viina(path: Path, oblast_names: dict[str, str]) -> pl.DataFrame:
    """VIINA events as (event_date ISO string, oblast in gazetteer naming, t_mil)."""
    with zipfile.ZipFile(path) as z:
        (name,) = [n for n in z.namelist() if n.endswith(".csv")]
        raw = pl.read_csv(io.BytesIO(z.read(name)), infer_schema_length=0)
    unknown = set(raw["ADM1_NAME"].drop_nulls().unique().to_list()) - set(oblast_names)
    if unknown:
        raise ValueError(f"VIINA oblasts missing from config viina.oblast_names: {unknown}")
    return raw.filter(pl.col("ADM1_NAME").is_not_null()).select(
        pl.col("date").str.to_date("%Y%m%d").cast(pl.String).alias("event_date"),
        pl.col("ADM1_NAME").replace_strict(oblast_names).alias("oblast"),
        (pl.col("t_mil_b") == "1").alias("t_mil"),
    )


def covered_days(report_dates: list[str], start: str, end: str) -> list[str]:
    """Event dates the GSU reports cover (report date minus one day), inside the window."""
    days = {(date.fromisoformat(d) - timedelta(days=1)).isoformat() for d in report_dates}
    return sorted(d for d in days if start <= d <= end)


def ledger_events(ledger: pl.DataFrame, oblast_of: dict[str, str]) -> pl.DataFrame:
    """Located ledger events as (event_date, oblast); events without an oblast are dropped."""
    located = ledger.filter(pl.col("gazetteer_id").is_not_null())
    return located.select(
        pl.col("event_date").cast(pl.String),
        pl.col("gazetteer_id").replace_strict(oblast_of, default="").alias("oblast"),
    ).filter(pl.col("oblast") != "")


def daily_counts(events: pl.DataFrame, days: list[str]) -> pl.DataFrame:
    """(event_date, oblast, n) over the given days."""
    return (
        events.filter(pl.col("event_date").is_in(days))
        .group_by("event_date", "oblast")
        .len(name="n")
    )


def oblast_day_grid(a: pl.DataFrame, b: pl.DataFrame, days: list[str]) -> pl.DataFrame:
    """Every (day, oblast) for oblasts in either count table, with n_a and n_b (0 if absent)."""
    oblasts = sorted(set(a["oblast"].to_list()) | set(b["oblast"].to_list()))
    grid = pl.DataFrame({"event_date": days}).join(pl.DataFrame({"oblast": oblasts}), how="cross")
    for name, counts in (("n_a", a), ("n_b", b)):
        grid = grid.join(counts.rename({"n": name}), on=["event_date", "oblast"], how="left")
    return grid.with_columns(pl.col("n_a", "n_b").fill_null(0)).sort("event_date", "oblast")


def spearman(grid: pl.DataFrame) -> float | None:
    """Spearman rank correlation of n_a and n_b (ties get average ranks); None if undefined."""
    if grid.height < 2 or grid["n_a"].n_unique() < 2 or grid["n_b"].n_unique() < 2:
        return None
    return grid.select(pl.corr("n_a", "n_b", method="spearman")).item()


def compare(
    ledger: pl.DataFrame, viina: pl.DataFrame, oblast_of: dict[str, str], days: list[str]
) -> dict[str, Any]:
    """Correlation against all VIINA events and against military-operations events."""
    ours = daily_counts(ledger_events(ledger, oblast_of), days)
    out: dict[str, Any] = {"days": len(days), "ledger_events": int(ours["n"].sum())}
    for label, theirs in (("t_mil", viina.filter("t_mil")), ("all", viina)):
        grid = oblast_day_grid(ours, daily_counts(theirs, days), days)
        out[label] = {
            "rho": spearman(grid),
            "oblast_days": grid.height,
            "oblasts": grid["oblast"].n_unique(),
            "viina_events": int(grid["n_b"].sum()),
        }
    return out


def main(argv: list[str] | None = None) -> None:
    from eval.score import append_results
    from src.gazetteer import read_table
    from src.h2 import stamp
    from src.link import LEDGER

    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    cfg = load_config()
    path = fetch(cfg)
    viina = read_viina(path, cfg["viina"]["oblast_names"])
    ledger = pl.read_parquet(LEDGER)
    oblast_of = {p.gazetteer_id: p.oblast for p in read_table() if p.oblast}
    days = covered_days(ledger["report_date"].cast(pl.String).unique().to_list(),
                        str(cfg["corpus"]["start"]), str(cfg["corpus"]["end"]))  # fmt: skip
    res = compare(ledger, viina, oblast_of, days)
    print(f"{res['days']} covered days, {res['ledger_events']} located ledger events")
    rows = []
    for label in ("t_mil", "all"):
        r = res[label]
        print(f"  VIINA {label}: Spearman {r['rho']} over {r['oblast_days']} oblast-days "
              f"({r['oblasts']} oblasts, {r['viina_events']} VIINA events)")  # fmt: skip
        rows.append({"metric": f"viina_spearman_{label}",
                     "value": "" if r["rho"] is None else round(r["rho"], 4),
                     "n": r["oblast_days"]})  # fmt: skip
    note = f"VIINA {cfg['viina']['file']} oid {cfg['viina']['oid'][:12]}; {res['days']} days"
    append_results(stamp(rows, cfg, cfg["ledger"]["system"], note))
    print(f"{len(rows)} rows appended to eval/results.csv")


if __name__ == "__main__":
    main()
