"""Linking rules 7a and 7b (SPEC.md section 5.2).

    uv run python -m src.link     # reads data/ledger.parquet, writes the two link tables

7a, duplicate clusters: two events are linked when they have the same event_type,
both have coordinates within `link.duplicate_km` of each other and their event
dates differ by at most `link.duplicate_days`, from any source. Pairs are found
with a DuckDB self-join; clusters are the connected components of the pair graph
(single linkage, so chains are possible: the largest cluster diameter is reported).

7b, confirmation links: each territorial_advance claim (ru_claimed or ua_claimed,
geo_precision 1, report date in the analysis window) is linked to the earliest-
reported geolocated_confirmed territorial_advance with the same gazetteer_id and
actor, reported 0 to `link.confirmation_days` days after the claim. Lag is in
report days. Claims with geo_precision > 1 are excluded and counted.

Outputs (git-ignored, no source text): data/links_duplicates.parquet
(event_id, cluster_id) and data/links_confirmations.parquet (one row per claim).
"""

from __future__ import annotations

import argparse
from itertools import combinations
from typing import Any

import duckdb
import polars as pl

from src.collect import DATA, ROOT
from src.config import load_config

LEDGER = DATA / "ledger.parquet"
DUPLICATES = DATA / "links_duplicates.parquet"
CONFIRMATIONS = DATA / "links_confirmations.parquet"
CLAIM_STATUSES = ("ru_claimed", "ua_claimed")


def haversine_sql(a: str, b: str) -> str:
    """DuckDB expression for the great-circle distance in km between rows `a` and `b`.

    Same formula and Earth radius as eval/score.py `haversine_km`.
    """
    return (
        f"2 * 6371.0088 * asin(sqrt("
        f"pow(sin(radians({b}.lat - {a}.lat) / 2), 2) + "
        f"cos(radians({a}.lat)) * cos(radians({b}.lat)) * "
        f"pow(sin(radians({b}.lon - {a}.lon) / 2), 2)))"
    )


def duplicate_edges(ledger: pl.DataFrame, km: float, days: int) -> list[tuple[str, str]]:
    """Pairs of event_ids linked by rule 7a, each pair once (smaller id first)."""
    con = duckdb.connect()
    con.register("ledger", ledger.select("event_id", "event_type", "event_date", "lat", "lon"))
    rows = con.execute(
        f"""
        with located as (
            select event_id, event_type, cast(event_date as date) as d, lat, lon
            from ledger where lat is not null and lon is not null
        )
        select a.event_id, b.event_id
        from located a join located b
          on a.event_type = b.event_type
         and a.event_id < b.event_id
         and abs(date_diff('day', a.d, b.d)) <= ?
        where {haversine_sql("a", "b")} <= ?
        order by 1, 2
        """,
        [days, km],
    ).fetchall()
    return [(a, b) for a, b in rows]


def components(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Connected components by union-find: {event_id: cluster number}.

    Clusters are numbered 0, 1, ... in order of their smallest event_id, so the
    numbering does not depend on edge order. Unlinked events get a cluster of one.
    """
    parent = {i: i for i in ids}

    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path halving keeps the trees shallow
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = sorted({root(i) for i in ids})
    number = {r: n for n, r in enumerate(roots)}
    return {i: number[root(i)] for i in ids}


def cluster_table(ledger: pl.DataFrame, km: float, days: int) -> pl.DataFrame:
    """(event_id, cluster_id, cluster_size) for every ledger event."""
    ids = ledger["event_id"].to_list()
    clusters = components(ids, duplicate_edges(ledger, km, days))
    frame = pl.DataFrame({"event_id": ids, "cluster_id": [clusters[i] for i in ids]})
    return frame.with_columns(pl.len().over("cluster_id").alias("cluster_size"))


def cluster_diameters(ledger: pl.DataFrame, clusters: pl.DataFrame) -> pl.DataFrame:
    """Per cluster of two or more: size, largest pairwise distance (km) and date span (days)."""
    from eval.score import haversine_km

    joined = ledger.join(clusters, on="event_id").filter(pl.col("cluster_size") > 1)
    out = []
    for (cid,), group in joined.group_by("cluster_id"):
        points = list(zip(group["lat"].to_list(), group["lon"].to_list(), strict=True))
        far = max((haversine_km(*p, *q) for p, q in combinations(points, 2)), default=0.0)
        dates = group["event_date"].cast(pl.String).str.to_date()
        out.append({"cluster_id": cid, "size": group.height, "diameter_km": far,
                    "span_days": (dates.max() - dates.min()).days})  # fmt: skip
    schema = {"cluster_id": pl.Int64, "size": pl.Int64, "diameter_km": pl.Float64,
              "span_days": pl.Int64}  # fmt: skip
    return pl.DataFrame(out, schema=schema).sort("cluster_id")


def confirmation_links(
    ledger: pl.DataFrame, start: str, end: str, max_days: int
) -> tuple[pl.DataFrame, int]:
    """Rule 7b. Returns one row per eligible claim, and the number excluded for precision > 1.

    Columns: claim_id, report_id, report_date, sector, actor, epistemic_status,
    gazetteer_id, confirm_id, confirm_report_date, lag_days (null when unconfirmed).
    The earliest-reported confirmation wins; ties go to the smaller event_id.
    """
    con = duckdb.connect()
    con.register("ledger", ledger)
    claim_filter = f"""
        event_type = 'territorial_advance'
        and epistemic_status in {CLAIM_STATUSES}
        and cast(report_date as date) between cast(? as date) and cast(? as date)
    """
    excluded = con.execute(
        f"select count(*) from ledger where {claim_filter} "
        "and (geo_precision is null or geo_precision > 1)",
        [start, end],
    ).fetchall()[0][0]
    links = con.sql(
        f"""
        with claims as (
            select event_id, report_id, cast(report_date as date) as rd, sector, actor,
                   epistemic_status, gazetteer_id
            from ledger where {claim_filter} and geo_precision = 1
        ),
        confirms as (
            select event_id, cast(report_date as date) as rd, actor, gazetteer_id
            from ledger
            where event_type = 'territorial_advance'
              and epistemic_status = 'geolocated_confirmed'
              and gazetteer_id is not null
        ),
        ranked as (
            select c.event_id as claim_id, k.event_id as confirm_id, k.rd as confirm_rd,
                   row_number() over (partition by c.event_id order by k.rd, k.event_id) as n
            from claims c join confirms k
              on k.gazetteer_id = c.gazetteer_id
             and k.actor is not distinct from c.actor
             and k.rd between c.rd and c.rd + to_days(cast(? as integer))
        )
        select c.event_id as claim_id, c.report_id, c.rd as report_date, c.sector, c.actor,
               c.epistemic_status, c.gazetteer_id, r.confirm_id,
               r.confirm_rd as confirm_report_date,
               date_diff('day', c.rd, r.confirm_rd) as lag_days
        from claims c left join ranked r on r.claim_id = c.event_id and r.n = 1
        order by c.event_id
        """,
        params=[start, end, max_days],
    ).pl()
    return links, int(excluded)


def run(ledger: pl.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    """Both rules on a ledger; returns the tables and the numbers worth printing."""
    link = cfg["link"]
    clusters = cluster_table(ledger, link["duplicate_km"], link["duplicate_days"])
    diam = cluster_diameters(ledger, clusters)
    links, excluded = confirmation_links(
        ledger, str(cfg["corpus"]["start"]), str(cfg["corpus"]["analysis_end"]),
        link["confirmation_days"],
    )  # fmt: skip
    return {
        "clusters": clusters,
        "diameters": diam,
        "confirmations": links,
        "excluded_precision": excluded,
        "n_clusters_multi": diam.height,
        "max_diameter_km": diam["diameter_km"].max() if diam.height else None,
        "max_span_days": diam["span_days"].max() if diam.height else None,
    }


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    cfg = load_config()
    ledger = pl.read_parquet(LEDGER)
    out = run(ledger, cfg)
    out["clusters"].write_parquet(DUPLICATES)
    out["confirmations"].write_parquet(CONFIRMATIONS)
    linked = out["clusters"].filter(pl.col("cluster_size") > 1).height
    conf = out["confirmations"]
    print(
        f"7a: {ledger.height} events; {linked} in {out['n_clusters_multi']} clusters of 2+; "
        f"largest diameter {out['max_diameter_km']} km, "
        f"longest span {out['max_span_days']} days"
    )
    print(f"7b: {conf.height} eligible claims, {conf['confirm_id'].is_not_null().sum()} confirmed "
          f"within {cfg['link']['confirmation_days']} days; {out['excluded_precision']} claims "
          "excluded for geo_precision > 1")  # fmt: skip
    print(f"wrote {DUPLICATES.relative_to(ROOT)} and {CONFIRMATIONS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
