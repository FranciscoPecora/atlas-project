"""Claimline event schema. Normative copy lives in SPEC.md section 2."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(StrEnum):
    ground_assault = "ground_assault"
    territorial_advance = "territorial_advance"
    withdrawal = "withdrawal"
    missile_strike = "missile_strike"
    drone_strike = "drone_strike"
    air_strike = "air_strike"
    shelling = "shelling"
    air_defence_interception = "air_defence_interception"
    force_movement = "force_movement"
    logistics_or_infrastructure_strike = "logistics_or_infrastructure_strike"
    naval_event = "naval_event"
    other = "other"


class EpistemicStatus(StrEnum):
    ru_claimed = "ru_claimed"
    ua_claimed = "ua_claimed"
    third_party_claimed = "third_party_claimed"
    geolocated_confirmed = "geolocated_confirmed"
    analyst_assessed = "analyst_assessed"


class Side(StrEnum):
    RU = "RU"
    UA = "UA"
    other = "other"


def _casefold_enum(enum_cls: type[StrEnum], value: object) -> object:
    """Map a string onto an enum member ignoring case. The API does not guarantee enum case."""
    if isinstance(value, str):
        for member in enum_cls:
            if member.value.lower() == value.strip().lower():
                return member
    return value


class UnitMention(BaseModel):
    name: str = Field(description="Unit name exactly as written in the evidence quote")
    echelon: str | None = Field(None, description="e.g. brigade, regiment, battalion, division")
    branch: str | None = Field(None, description="e.g. VDV, naval infantry, motorized rifle")


class ExtractedEvent(BaseModel):
    """What the extraction model returns. No offsets, no coordinates, no report metadata."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    epistemic_status: EpistemicStatus
    claim_source: str | None = Field(
        None, description="Who made the claim as the text names them, e.g. 'Russian MoD'"
    )
    actor: Side | None = None
    actor_text: str | None = None
    target: Side | None = None
    target_text: str | None = None
    location_text: str | None = Field(
        None, description="Place name exactly as written; must appear inside evidence_quote"
    )
    geo_precision: int | None = Field(
        None, description="1 settlement, 2 direction or area, 3 oblast"
    )
    event_date: date
    units: list[UnitMention] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    quantity: int | None = Field(None, description="Must appear inside evidence_quote")
    evidence_quote: str = Field(description="Exact contiguous text copied from the section")

    @field_validator("event_type", mode="before")
    @classmethod
    def _event_type_case(cls, v: object) -> object:
        return _casefold_enum(EventType, v)

    @field_validator("epistemic_status", mode="before")
    @classmethod
    def _status_case(cls, v: object) -> object:
        return _casefold_enum(EpistemicStatus, v)

    @field_validator("actor", "target", mode="before")
    @classmethod
    def _side_case(cls, v: object) -> object:
        return _casefold_enum(Side, v)

    @field_validator("geo_precision")
    @classmethod
    def _precision_range(cls, v: int | None) -> int | None:
        if v is not None and v not in (1, 2, 3):
            raise ValueError("geo_precision must be 1, 2 or 3")
        return v

    @field_validator("quantity")
    @classmethod
    def _quantity_nonneg(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("quantity must be >= 0")
        return v

    @field_validator("evidence_quote")
    @classmethod
    def _quote_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence_quote must not be empty")
        return v


class ExtractionResult(BaseModel):
    """Top-level output_format for client.messages.parse: one call per section."""

    events: list[ExtractedEvent]


class LedgerEvent(ExtractedEvent):
    """One row of the ledger. Fields below are filled by code, never by a model."""

    event_id: str
    report_id: str
    source: Annotated[str, Field(pattern="^(isw|gsu)$")]
    section: str
    sector: str
    report_date: date
    lat: float | None = None
    lon: float | None = None
    gazetteer_id: str | None = None
    unit_ids: list[str] = Field(default_factory=list)
    evidence_start: int
    evidence_end: int
    text_sha256: str
    source_url: str
    footnote_ref: str | None = None
    system: str
    run_id: str


PUBLIC_EXCLUDED_FIELDS = frozenset({"evidence_quote"})


def extraction_json_schema() -> dict:
    """JSON Schema sent to the API as the output format. Must equal SPEC.md Appendix B."""
    return ExtractionResult.model_json_schema()


def main() -> None:
    import json
    from pathlib import Path

    out = Path("schema/extraction_result.schema.json")
    out.write_text(json.dumps(extraction_json_schema(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
