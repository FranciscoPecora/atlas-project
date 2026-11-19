"""Public ledger export: the ledger without any source text (CLAUDE.md hard rule).

    uv run python -m src.release   # data/ledger.parquet + link tables -> release/

Writes release/ledger_public.parquet, release/ledger_public.schema.json and
release/DATA_DICTIONARY.md. The public file is built from a whitelist (the fields of
`PublicEvent`), not by dropping a blacklist, so a field added to the ledger later
stays private until someone adds it here on purpose.

Left out because they hold words copied from the reports: evidence_quote,
location_text, claim_source, actor_text, target_text, equipment, units, section.
The map label is the gazetteer's standard name (GeoNames or OpenStreetMap), looked
up by gazetteer_id, which is not report text. `check_public` refuses a frame whose
strings hold Cyrillic letters or any of the private free-text values.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from src.collect import DATA, ROOT
from src.link import CONFIRMATIONS, DUPLICATES, LEDGER
from src.schema import EpistemicStatus, EventType, Side

RELEASE = ROOT / "release"
PUBLIC = RELEASE / "ledger_public.parquet"
SCHEMA = RELEASE / "ledger_public.schema.json"
DICTIONARY = RELEASE / "DATA_DICTIONARY.md"
GAZETTEER = DATA / "gazetteer.parquet"

PRIVATE_TEXT_FIELDS = ("evidence_quote", "location_text", "claim_source", "actor_text",
                       "target_text", "equipment", "units", "section")  # fmt: skip
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


class PublicEvent(BaseModel):
    """One row of the public ledger. No field holds text copied from a report."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(description="Stable id: report id, system, index in the report")
    report_id: str = Field(description="Source and report date, e.g. gsu-2026-08-01")
    source: str = Field(description="gsu (Ukrainian General Staff via ArmyInform) or isw")
    report_date: date = Field(description="Publication date of the report")
    event_date: date = Field(description="Date the event happened (default: report date - 1)")
    event_type: EventType = Field(description="One of 12 types (annotation guideline)")
    epistemic_status: EpistemicStatus = Field(description="Who asserts the event, and how")
    actor: Side | None = Field(None, description="Side that acted: RU, UA or other")
    target: Side | None = Field(None, description="Side acted upon")
    geo_precision: int | None = Field(None, description="1 settlement, 2 area/direction, 3 oblast")
    quantity: int | None = Field(None, description="Count stated in the report, if any")
    gazetteer_id: str | None = Field(None, description="gn:<GeoNames id> or osm:<OSM node id>")
    place_name: str | None = Field(None, description="Standard name from the gazetteer (Latin)")
    oblast: str | None = Field(None, description="Oblast of the gazetteer place")
    lat: float | None = Field(None, description="Latitude from the gazetteer, never the model")
    lon: float | None = Field(None, description="Longitude from the gazetteer, never the model")
    cluster_id: int | None = Field(None, description="Rule 7a duplicate cluster")
    cluster_size: int | None = Field(None, description="Events in that cluster")
    confirmed_by: str | None = Field(None, description="Rule 7b: event_id of the confirmation")
    lag_days: int | None = Field(None, description="Rule 7b: report days from claim to confirm")
    evidence_start: int = Field(description="Start offset of the evidence in the cleaned text")
    evidence_end: int = Field(description="End offset (exclusive)")
    text_sha256: str = Field(description="SHA-256 of the cleaned report text the offsets index")
    source_url: str = Field(description="URL of the report")
    system: str = Field(description="Pipeline version that produced the row, e.g. S3-H")
    run_id: str = Field(description="Run that produced the row")


PUBLIC_FIELDS = tuple(PublicEvent.model_fields)


def public_frame(
    ledger: pl.DataFrame,
    gazetteer: pl.DataFrame,
    duplicates: pl.DataFrame,
    confirmations: pl.DataFrame,
) -> pl.DataFrame:
    """Join gazetteer names and link results onto the ledger, keep the public fields."""
    places = gazetteer.select("gazetteer_id", pl.col("name").alias("place_name"), "oblast")
    dup = duplicates.select("event_id", "cluster_id", pl.col("cluster_size").cast(pl.Int64))
    conf = confirmations.select(
        pl.col("claim_id").alias("event_id"),
        pl.col("confirm_id").cast(pl.String).alias("confirmed_by"),
        pl.col("lag_days").cast(pl.Int64),
    )
    out = (
        ledger.join(places, on="gazetteer_id", how="left")
        .join(dup, on="event_id", how="left")
        .join(conf, on="event_id", how="left")
        .with_columns(
            pl.col("report_date").cast(pl.String).str.to_date(),
            pl.col("event_date").cast(pl.String).str.to_date(),
        )
    )
    return out.select(PUBLIC_FIELDS).sort("report_date", "event_id")


def private_values(ledger: pl.DataFrame) -> set[str]:
    """Every free-text string in the private ledger (list fields flattened)."""
    values: set[str] = set()
    for col in PRIVATE_TEXT_FIELDS:
        if col not in ledger.columns:
            continue
        for v in ledger[col].to_list():
            items = v if isinstance(v, list) else [v]
            values |= {str(x) for x in items if isinstance(x, str) and x.strip()}
    return values


def check_public(frame: pl.DataFrame, private: set[str]) -> None:
    """Raise if a public frame could carry source text."""
    extra = set(frame.columns) - set(PUBLIC_FIELDS)
    if extra:
        raise ValueError(f"non-public columns: {sorted(extra)}")
    for col in frame.columns:
        if frame[col].dtype != pl.String:
            continue
        for v in frame[col].drop_nulls().unique().to_list():
            if CYRILLIC.search(v):
                raise ValueError(f"Cyrillic text in public column {col}: row value withheld")
            if v in private:
                raise ValueError(f"public column {col} repeats a private free-text value")


def validate_rows(frame: pl.DataFrame) -> int:
    """Validate every row against PublicEvent; return the count."""
    for row in frame.to_dicts():
        PublicEvent.model_validate(row)
    return frame.height


def dictionary_markdown() -> str:
    """DATA_DICTIONARY.md, generated from the PublicEvent field descriptions."""
    lines = [
        "# Data dictionary: ledger_public.parquet",
        "",
        "One row per event extracted from a daily report. Generated by `make release`",
        "from `src/release.py`; the JSON Schema is `ledger_public.schema.json`.",
        "",
        "The file holds no text from the reports: the evidence is given as character",
        "offsets into the cleaned report text, with that text's SHA-256 and the report",
        "URL. Rebuild the cleaned text with `make data` and check the hash to read it.",
        "",
        "| Field | Type | Meaning |",
        "| --- | --- | --- |",
    ]
    schema = PublicEvent.model_json_schema()
    for name, info in PublicEvent.model_fields.items():
        prop = schema["properties"][name]
        options = prop.get("anyOf", [prop])
        kinds = [p.get("type") or p.get("$ref", "").split("/")[-1] for p in options]
        kind = " or ".join(k for k in kinds if k) or "string"
        if prop.get("format") == "date":
            kind = "date"
        lines.append(f"| `{name}` | {kind} | {info.description} |")
    lines += [
        "",
        "## Sources and licences",
        "",
        "- Reports: Ukrainian General Staff operational updates as republished by",
        "  ArmyInform (armyinform.com.ua), CC BY 4.0.",
        "- Places: GeoNames (CC BY 4.0) and OpenStreetMap (ODbL), merged in",
        "  `src/gazetteer.py`.",
        "- Rows are produced by a language-model pipeline and contain errors; see",
        "  FAILURES.md and the README for measured accuracy.",
        "",
    ]
    return "\n".join(lines)


def write_release(frame: pl.DataFrame, folder: Path = RELEASE) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / PUBLIC.name, folder / SCHEMA.name, folder / DICTIONARY.name]
    frame.write_parquet(paths[0])
    schema = PublicEvent.model_json_schema()
    paths[1].write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
    paths[2].write_text(dictionary_markdown())
    return paths


def build(folder: Path = RELEASE) -> tuple[pl.DataFrame, list[Path]]:
    ledger = pl.read_parquet(LEDGER)
    frame = public_frame(
        ledger,
        pl.read_parquet(GAZETTEER),
        pl.read_parquet(DUPLICATES),
        pl.read_parquet(CONFIRMATIONS),
    )
    check_public(frame, private_values(ledger))
    validate_rows(frame)
    return frame, write_release(frame, folder)


def summary(frame: pl.DataFrame) -> str:
    located = frame["lat"].is_not_null().sum()
    days = f"{frame['report_date'].min()} to {frame['report_date'].max()}"
    return (f"{frame.height} public events, {located} located, reports {days}; "
            f"{frame['confirmed_by'].is_not_null().sum()} confirmation links")  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    frame, paths = build()
    print(summary(frame))
    for p in paths:
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
