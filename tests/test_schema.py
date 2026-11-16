import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schema import (
    EpistemicStatus,
    EventType,
    ExtractedEvent,
    ExtractionResult,
    LedgerEvent,
    extraction_json_schema,
)

ROOT = Path(__file__).resolve().parent.parent


def spec_appendix_b() -> dict:
    spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    section = spec.split("## Appendix B", 1)[1]
    block = re.search(r"```json\n(.*?)\n```", section, re.DOTALL)
    assert block, "Appendix B JSON block not found"
    return json.loads(block.group(1))


def test_exported_schema_matches_spec_appendix_b():
    assert extraction_json_schema() == spec_appendix_b()


def test_schema_respects_api_limits():
    schema = extraction_json_schema()
    optional = unions = 0
    for d in schema["$defs"].values():
        props = d.get("properties", {})
        required = set(d.get("required", []))
        optional += sum(1 for k in props if k not in required)
        unions += sum(1 for v in props.values() if "anyOf" in v)
    assert optional <= 24
    assert unions <= 16


def minimal(**kw):
    base = {
        "event_type": "ground_assault",
        "epistemic_status": "ua_claimed",
        "event_date": "2026-07-28",
        "evidence_quote": "ворог атакував",
    }
    return {**base, **kw}


def test_enums_accept_any_case():
    e = ExtractedEvent.model_validate(
        minimal(event_type="Ground_Assault", epistemic_status="RU_CLAIMED", actor="ru")
    )
    assert e.event_type is EventType.ground_assault
    assert e.epistemic_status is EpistemicStatus.ru_claimed
    assert e.actor == "RU"


@pytest.mark.parametrize(
    "field,value", [("geo_precision", 4), ("quantity", -1), ("evidence_quote", " ")]
)
def test_ranges_are_validated_after_parsing(field, value):
    with pytest.raises(ValidationError):
        ExtractedEvent.model_validate(minimal(**{field: value}))


def test_model_output_cannot_carry_offsets_or_coordinates():
    with pytest.raises(ValidationError):
        ExtractedEvent.model_validate(minimal(evidence_start=3))
    with pytest.raises(ValidationError):
        ExtractedEvent.model_validate(minimal(lat=48.1))


def test_extraction_result_allows_empty_list():
    assert ExtractionResult.model_validate({"events": []}).events == []


def test_ledger_event_adds_code_computed_fields():
    row = LedgerEvent.model_validate(
        minimal(
            event_id="e1",
            report_id="gsu-2026-07-29",
            source="gsu",
            section="FULL",
            sector="FULL",
            report_date="2026-07-29",
            evidence_start=10,
            evidence_end=24,
            text_sha256="ab" * 32,
            source_url="https://armyinform.com.ua/x/",
            system="S2",
            run_id="r1",
        )
    )
    assert row.evidence_end - row.evidence_start == 14
    with pytest.raises(ValidationError):
        LedgerEvent.model_validate({**row.model_dump(), "source": "telegram"})
