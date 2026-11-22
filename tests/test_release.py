import json

import polars as pl
import pytest

from src import release


def ledger_row(i: int, **kw) -> dict:
    row = {
        "event_type": "ground_assault", "epistemic_status": "ua_claimed",
        "claim_source": "General Staff", "actor": "RU", "actor_text": "окупанти",
        "target": None, "target_text": None, "location_text": "Ясного",
        "geo_precision": 1, "event_date": "2026-08-01", "units": [], "equipment": ["танк"],
        "quantity": None, "evidence_quote": "ворог атакував в районі Ясного",
        "event_id": f"gsu-2026-08-02:S3-H:{i}", "report_id": "gsu-2026-08-02",
        "source": "gsu", "section": "FULL", "sector": "FULL", "report_date": "2026-08-02",
        "lat": 48.0, "lon": 37.0, "gazetteer_id": "gn:1", "unit_ids": [],
        "evidence_start": 10, "evidence_end": 40, "text_sha256": "a" * 64,
        "source_url": "https://armyinform.com.ua/x", "footnote_ref": None,
        "system": "S3-H", "run_id": "run1",
    }  # fmt: skip
    row.update(kw)
    return row


GAZ = pl.DataFrame({"gazetteer_id": ["gn:1"], "name": ["Yasne"], "oblast": ["Donetsk"]})
DUP = pl.DataFrame({"event_id": ["gsu-2026-08-02:S3-H:0", "gsu-2026-08-02:S3-H:1"],
                    "cluster_id": [0, 1], "cluster_size": [1, 1]},
                   schema_overrides={"cluster_size": pl.UInt32})  # fmt: skip
CONF = pl.DataFrame(schema={"claim_id": pl.String, "confirm_id": pl.String,
                            "lag_days": pl.Int64})  # fmt: skip


def frame():
    ledger = pl.DataFrame([ledger_row(0), ledger_row(1, gazetteer_id=None, lat=None, lon=None)])
    return ledger, release.public_frame(ledger, GAZ, DUP, CONF)


def test_public_fields_hold_no_private_text_field():
    assert not set(release.PUBLIC_FIELDS) & set(release.PRIVATE_TEXT_FIELDS)
    assert "evidence_quote" not in release.PUBLIC_FIELDS


def test_public_frame_keeps_whitelist_and_adds_gazetteer_name():
    ledger, out = frame()
    assert out.columns == list(release.PUBLIC_FIELDS)
    assert out["place_name"].to_list() == ["Yasne", None]
    assert out["cluster_id"].to_list() == [0, 1]
    assert out["confirmed_by"].null_count() == 2
    assert release.validate_rows(out) == 2
    release.check_public(out, release.private_values(ledger))


def test_private_values_flattens_lists():
    ledger, _ = frame()
    vals = release.private_values(ledger)
    assert {"Ясного", "танк", "General Staff", "окупанти"} <= vals


def test_check_public_refuses_cyrillic_and_private_values_and_extra_columns():
    ledger, out = frame()
    private = release.private_values(ledger)
    with pytest.raises(ValueError, match="Cyrillic"):
        release.check_public(out.with_columns(place_name=pl.lit("Ясне")), private)
    with pytest.raises(ValueError, match="private free-text"):
        release.check_public(out.with_columns(place_name=pl.lit("General Staff")), private)
    with pytest.raises(ValueError, match="non-public"):
        release.check_public(ledger.select("event_id", "evidence_quote"), private)


def test_write_release_files(tmp_path):
    _, out = frame()
    paths = release.write_release(out, tmp_path)
    assert [p.name for p in paths] == ["ledger_public.parquet", "ledger_public.schema.json",
                                       "DATA_DICTIONARY.md"]  # fmt: skip
    assert pl.read_parquet(paths[0]).height == 2
    schema = json.loads(paths[1].read_text())
    assert schema["additionalProperties"] is False and "evidence_quote" not in schema["properties"]
    text = paths[2].read_text()
    assert all(f"`{f}`" in text for f in release.PUBLIC_FIELDS)
    assert "CC BY 4.0" in text


def test_summary_line():
    _, out = frame()
    assert release.summary(out).startswith("2 public events, 1 located")


def test_latin_transliterates_only_cyrillic_names():
    assert release.latin("Сумська") == "Sumska"
    assert release.latin("Новоселівка") == "Novoselivka"
    assert release.latin("Yasne") == "Yasne" and release.latin(None) is None


def test_air_nights_tells_hits_from_launches():
    def af(etype, qty, quote):
        return ledger_row(0, source="af", event_type=etype, quantity=qty, evidence_quote=quote,
                          event_date="2026-08-01")  # fmt: skip

    ledger = pl.DataFrame([
        af("drone_strike", 80, "противник атакував 80 ударними БПЛА"),
        af("drone_strike", 14, "Зафіксовано влучання 14 ударних БПЛА"),
        af("missile_strike", 2, "двома ракетами Іскандер-М"),
        af("missile_strike", 1, "влучання ракети"),
        af("air_defence_interception", 65, "збила 65"),
        ledger_row(1),
    ])  # fmt: skip
    (row,) = release.air_nights(ledger).to_dicts()
    assert row == {"night": "2026-08-01", "drones_launched": 80, "missiles_launched": 2,
                   "drones_hit": 14, "missiles_hit": 1, "shot_down": 65}  # fmt: skip
