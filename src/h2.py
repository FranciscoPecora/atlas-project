"""Hypothesis H2: how often, and how fast, Russian-claimed advances are confirmed (SPEC 5.3).

    uv run python -m src.h2      # reads data/ledger.parquet, appends rows to eval/results.csv

Claims are rule 7b's claims with epistemic_status ru_claimed and actor RU. For each
window in `link.report_windows_days` (7, 14, 30) the share confirmed within that many
report days is given with a 95% percentile bootstrap interval that resamples the
claims' reports (SPEC 5.4: 2,000 resamples, seed 20261116). The median lag of the
confirmed claims is given per sector, with the same kind of interval. H2 holds if
the 14-day share's point estimate is below 0.50.

With no eligible claim every number is undefined (None), and the output says so.
"""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from statistics import median
from typing import Any

import polars as pl

from src.collect import DATA, ROOT
from src.config import config_hash, load_config
from src.link import LEDGER, confirmation_links

Row = dict[str, Any]


def h2_claims(links: pl.DataFrame) -> list[Row]:
    """The 7b claims H2 is about: ru_claimed with actor RU."""
    keep = links.filter((pl.col("epistemic_status") == "ru_claimed") & (pl.col("actor") == "RU"))
    return keep.to_dicts()


def confirmed_share(claims: list[Row], window: int) -> float | None:
    """Share of claims confirmed with lag <= window days; None when there are no claims."""
    if not claims:
        return None
    hits = sum(c["lag_days"] is not None and c["lag_days"] <= window for c in claims)
    return hits / len(claims)


def median_lag(claims: list[Row]) -> float | None:
    """Median lag in days over the confirmed claims; None when none is confirmed."""
    lags = [c["lag_days"] for c in claims if c["lag_days"] is not None]
    return float(median(lags)) if lags else None


def bootstrap(
    rows: list[Row],
    stat: Callable[[list[Row]], float | None],
    unit: str = "report_id",
    resamples: int = 2000,
    seed: int = 20261116,
) -> tuple[float | None, float | None]:
    """95% percentile interval of `stat`, resampling whole `unit`s with replacement.

    Resamples where the statistic is undefined (say, no confirmed claim for a median)
    are left out of the percentiles. (None, None) when no resample is defined.
    """
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        groups[r[unit]].append(r)
    keys = sorted(groups)
    if not keys:
        return None, None
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        drawn = [r for _ in keys for r in groups[rng.choice(keys)]]
        v = stat(drawn)
        if v is not None:
            values.append(v)
    if not values:
        return None, None
    values.sort()
    n = len(values)
    return values[int(0.025 * n)], values[min(n - 1, int(0.975 * n))]


def h2(links: pl.DataFrame, windows: list[int], resamples: int, seed: int) -> dict[str, Any]:
    """All H2 numbers from a 7b link table."""
    claims = h2_claims(links)
    shares = {}
    for w in windows:
        low, high = bootstrap(claims, lambda c, w=w: confirmed_share(c, w), resamples=resamples,
                              seed=seed)  # fmt: skip
        shares[w] = {"share": confirmed_share(claims, w), "low": low, "high": high}
    by_sector: dict[str, list[Row]] = defaultdict(list)
    for c in claims:
        by_sector[c["sector"]].append(c)
    lags = {}
    for sector, rows in sorted(by_sector.items()):
        low, high = bootstrap(rows, median_lag, resamples=resamples, seed=seed)
        confirmed = sum(r["lag_days"] is not None for r in rows)
        lags[sector] = {"median": median_lag(rows), "low": low, "high": high,
                        "n_claims": len(rows), "n_confirmed": confirmed}  # fmt: skip
    share14 = shares.get(14, {}).get("share")
    return {
        "n_claims": len(claims),
        "n_reports": len({c["report_id"] for c in claims}),
        "n_confirmed_any": sum(c["lag_days"] is not None for c in claims),
        "shares": shares,
        "lags": lags,
        "holds": None if share14 is None else share14 < 0.5,
    }


def describe(res: dict[str, Any], excluded: int) -> str:
    """Plain-text report of the H2 numbers."""

    def num(x: float | None, fmt: str = ".3f") -> str:
        return "undefined" if x is None else format(x, fmt)

    lines = [f"H2 claims (ru_claimed, actor RU, geo_precision 1, analysis window): "
             f"{res['n_claims']} in {res['n_reports']} reports; "
             f"{excluded} territorial-advance claims excluded for geo_precision > 1"]  # fmt: skip
    for w, s in res["shares"].items():
        lines.append(f"  confirmed within {w} days: {num(s['share'])} "
                     f"[{num(s['low'])}, {num(s['high'])}]")  # fmt: skip
    for sector, s in res["lags"].items():
        lines.append(f"  median lag, {sector}: {num(s['median'], '.1f')} days "
                     f"[{num(s['low'], '.1f')}, {num(s['high'], '.1f')}] "
                     f"({s['n_confirmed']} of {s['n_claims']} confirmed)")  # fmt: skip
    verdict = {None: "undefined (no eligible claim)", True: "holds", False: "does not hold"}
    lines.append(f"  H2 (14-day share < 0.50): {verdict[res['holds']]}")
    return "\n".join(lines)


def result_rows(res: dict[str, Any], excluded: int) -> list[Row]:
    """Rows for eval/results.csv (split 'corpus', system = the ledger's system)."""

    def val(x: float | None) -> Any:
        return "" if x is None else round(x, 4)

    n = res["n_claims"]
    rows = [{"metric": "h2_claims", "value": n, "n": res["n_reports"]},
            {"metric": "h2_excluded_geo_precision", "value": excluded, "n": ""}]  # fmt: skip
    for w, s in res["shares"].items():
        for key, suffix in (("share", ""), ("low", "_low"), ("high", "_high")):
            rows.append({"metric": f"h2_confirmed_{w}d{suffix}", "value": val(s[key]), "n": n})
    for sector, s in res["lags"].items():
        for key, suffix in (("median", ""), ("low", "_low"), ("high", "_high")):
            rows.append({"metric": f"h2_median_lag_{sector}{suffix}", "value": val(s[key]),
                         "n": s["n_confirmed"]})  # fmt: skip
    return rows


def stamp(rows: list[Row], cfg: dict[str, Any], system: str, note: str) -> list[Row]:
    """Add commit, config hash, date, split and system, as eval/score.py does."""
    import subprocess

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()  # fmt: skip
    base = {"commit": commit, "config_hash": config_hash(cfg),
            "date": date.today().isoformat(), "split": "corpus", "system": system,
            "config": note}  # fmt: skip
    return [{**base, **r} for r in rows]


def compute(ledger: pl.DataFrame, cfg: dict[str, Any]) -> tuple[dict[str, Any], int]:
    links, excluded = confirmation_links(
        ledger, str(cfg["corpus"]["start"]), str(cfg["corpus"]["analysis_end"]),
        cfg["link"]["confirmation_days"],
    )  # fmt: skip
    ev = cfg["eval"]
    res = h2(links, cfg["link"]["report_windows_days"], ev["bootstrap_resamples"], ev["seed"])
    return res, excluded


def main(argv: list[str] | None = None) -> None:
    from eval.score import append_results

    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    cfg = load_config()
    ledger = pl.read_parquet(LEDGER)
    res, excluded = compute(ledger, cfg)
    print(describe(res, excluded))
    sources = ",".join(sorted(ledger["source"].unique().to_list()))
    ev = cfg["eval"]
    note = (
        f"7b; windows {cfg['link']['report_windows_days']}; sources {sources}; "
        f"resamples={ev['bootstrap_resamples']} seed={ev['seed']}"
    )
    rows = stamp(result_rows(res, excluded), cfg, cfg["ledger"]["system"], note)
    append_results(rows)
    print(f"{len(rows)} rows appended to eval/results.csv (ledger {DATA.name}/{LEDGER.name})")


if __name__ == "__main__":
    main()
