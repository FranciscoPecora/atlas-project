import json
from datetime import date

import pytest
from pydantic import ValidationError

from src.labels import (
    NO_AID,
    SPEC,
    GoldUnit,
    attach_prefill,
    attach_reading_aid,
    control_task,
    export,
    gold_units,
    resolve_sectors,
    tasks_for_unit,
    with_control,
)


def test_rotation_table_parses_to_45_units_with_10_dev():
    units = gold_units(SPEC.read_text(encoding="utf-8"))
    assert len(units) == 45
    assert [u.row for u in units if u.split == "dev"] == list(range(1, 11))
    assert sum(u.source == "isw" for u in units) == 30
    assert sum(u.source == "gsu" for u in units) == 15
    assert units[0] == GoldUnit(1, date(2026, 7, 19), "isw", ("AIR", "RU_INTERIOR"), "dev")
    # dev is strictly earlier than test: the split is by time
    assert max(u.report_date for u in units if u.split == "dev") < min(
        u.report_date for u in units if u.split == "test"
    )


def test_absent_sector_is_replaced_by_next_in_permutation():
    available = {"AIR", "OSKIL", "KHARKIV", "NORTH"}
    # RU_INTERIOR absent -> next in PERM after it is OSKIL
    assert resolve_sectors(("AIR", "RU_INTERIOR"), available) == ["AIR", "OSKIL"]
    # replacement never duplicates a sector already drawn for the report
    assert resolve_sectors(("OSKIL", "RU_INTERIOR"), available) == ["OSKIL", "KHARKIV"]


def test_isw_task_holds_only_its_sector_text_and_offset():
    text = (
        "Title\n\n## Toplines\n\nTop.\n\n"
        "## Russian Supporting Effort: Northern Axis\n\nNorth body.\n"
    )
    unit = GoldUnit(4, date(2026, 7, 27), "isw", ("NORTH", "SOUTH"), "dev")
    tasks = tasks_for_unit(unit, text, "h", "u")
    assert [t["data"]["sector"] for t in tasks] == ["NORTH"]  # SOUTH absent, no fallback left
    d = tasks[0]["data"]
    assert text[d["unit_start"] :].startswith(d["text"])
    assert "Top." not in d["text"]


UNIT_TEXT = "Header.\nНа Оріхівському напрямку ворог 4 рази атакував біля Степового."
UNIT_START = 500


def ls_task(regions: list[dict], task_level: dict | None = None, split: str = "dev") -> dict:
    result = []
    for i, r in enumerate(regions):
        start, end = r.pop("span")
        val = {"start": start, "end": end, "text": UNIT_TEXT[start:end]}
        result.append(
            {
                "id": f"r{i}",
                "from_name": "event",
                "type": "labels",
                "value": {**val, "labels": ["Event"]},
            }
        )
        for name, v in r.items():
            if name in ("event_type", "epistemic_status", "actor", "target", "geo_precision"):
                item = {"type": "choices", "value": {**val, "choices": [v]}}
            elif name == "quantity":
                item = {"type": "number", "value": {**val, "number": v}}
            else:
                item = {"type": "textarea", "value": {**val, "text": [v]}}
            result.append({"id": f"r{i}", "from_name": name, **item})
    for name, v in (task_level or {}).items():
        kind = "number" if name == "minutes" else "choices"
        value = {"number": v} if kind == "number" else {"choices": [v]}
        result.append({"id": f"t-{name}", "from_name": name, "type": kind, "value": value})
    return {
        "data": {
            "text": UNIT_TEXT,
            "unit_start": UNIT_START,
            "report_id": "gsu-2026-07-29",
            "source": "gsu",
            "report_date": "2026-07-29",
            "sector": "FULL",
            "split": split,
            "text_sha256": "ab" * 32,
            "source_url": "https://armyinform.com.ua/x/",
        },
        "annotations": [{"result": result}],
    }


def good_region() -> dict:
    s = UNIT_TEXT.index("На")
    return {
        "span": (s, len(UNIT_TEXT)),
        "event_type": "ground_assault",
        "epistemic_status": "ua_claimed",
        "actor": "RU",
        "location_text": "Степового",
        "geo_precision": "2",
        "event_date": "2026-07-28",
        "quantity": 4,
        "equipment": "",
    }


def test_export_writes_offsets_into_report_and_no_quote(tmp_path):
    counts = export([ls_task([good_region()], {"minutes": 7, "pass": "1"})], tmp_path)
    assert counts == {"dev": 1}
    out = tmp_path / "dev" / "gsu-2026-07-29__FULL__pass1.jsonl"
    (rec,) = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    s = UNIT_TEXT.index("На")
    assert (rec["evidence_start"], rec["evidence_end"]) == (
        UNIT_START + s,
        UNIT_START + len(UNIT_TEXT),
    )
    assert "evidence_quote" not in rec
    assert "атакував" not in out.read_text(encoding="utf-8")  # no source text in gold files
    assert rec["geo_precision"] == 2 and rec["quantity"] == 4
    assert rec["minutes"] == 7 and rec["annotation_pass"] == 1
    assert rec["equipment"] == []


def test_export_routes_by_split_and_pass(tmp_path):
    export([ls_task([good_region()], {"pass": "2"}, split="test")], tmp_path)
    assert (tmp_path / "test" / "gsu-2026-07-29__FULL__pass2.jsonl").exists()
    assert not (tmp_path / "dev").exists()


def test_export_rejects_invalid_labels(tmp_path):
    bad = good_region()
    bad["event_date"] = "28 July"
    with pytest.raises(ValidationError):
        export([ls_task([bad])], tmp_path)


def _task(source: str, split: str) -> dict:
    return {"data": {"source": source, "split": split, "text": "x"}}


def test_reading_aid_only_on_gsu_dev_tasks():
    record = {"translation": "[1] starts: … \nEnglish", "places": "Покровськ = Pokrovsk"}
    dev = attach_reading_aid(_task("gsu", "dev"), record)["data"]
    assert dev["translation"] == record["translation"] and dev["places"] == record["places"]
    # a test unit never gets model output, even if a file exists (SPEC.md section 4)
    test = attach_reading_aid(_task("gsu", "test"), record)["data"]
    assert test["translation"] == NO_AID and test["places"] == ""
    isw = attach_reading_aid(_task("isw", "dev"), None)["data"]
    assert isw["translation"] == NO_AID


GSU_TEXT = (
    "Заголовок\n\n"
    "На Зеленому напрямку ворог тричі атакував у районах Нової Балки та Кам’янки.\n\n"
    "На Синьому напрямку окупанти атакували в бік Ясного.\n"
)


def _gsu_task(split: str) -> dict:
    unit = GoldUnit(2, date(2026, 7, 21), "gsu", ("FULL",), split)
    (task,) = tasks_for_unit(unit, GSU_TEXT, "ab" * 32, "https://armyinform.com.ua/x/")
    return task


def test_prefill_on_gsu_dev_only():
    dev = attach_prefill(_gsu_task("dev"), GSU_TEXT)
    assert dev["data"]["prelabel"] == "prelabel-rules-v1"
    labels = [r for r in dev["predictions"][0]["result"] if r["type"] == "labels"]
    assert len(labels) == 3
    test = attach_prefill(_gsu_task("test"), GSU_TEXT)
    assert "predictions" not in test and test["data"]["prelabel"] == ""


def test_control_task_comes_first_and_has_no_prefill():
    full = attach_prefill(_gsu_task("dev"), GSU_TEXT)
    tasks = with_control([full], "gsu-2026-07-21", [2])
    control = tasks[0]
    assert control["data"]["purpose"] == "control" and "predictions" not in control
    d = control["data"]
    assert GSU_TEXT[d["unit_start"] : d["unit_start"] + len(d["text"])] == d["text"]
    assert d["text"].startswith("На Зеленому") and d["text"].endswith("Кам’янки.")
    with pytest.raises(ValueError):
        control_task(attach_prefill(_gsu_task("test"), GSU_TEXT), [2])


def test_control_labels_go_to_check_dir_not_gold(tmp_path):
    task = ls_task([good_region()], {"pass": "1"})
    task["data"].update(purpose="control", sector="CONTROL", prelabel="")
    counts = export([task], tmp_path / "gold", tmp_path / "check")
    assert counts == {"control": 1}
    assert (tmp_path / "check" / "gsu-2026-07-29__CONTROL__pass1.jsonl").exists()
    assert not (tmp_path / "gold").exists()


def test_missing_sampled_reports_take_the_pinned_next_date():
    from src.labels import substitute

    spec = SPEC.read_text(encoding="utf-8")
    table = {u.report_id for u in gold_units(spec, substitutions=False)}
    used = {u.report_id: u for u in gold_units(spec)}
    assert "gsu-2026-08-22" in table and "gsu-2026-08-22" not in used
    assert used["gsu-2026-08-25"].split == "test" and "gsu-2026-08-31" in used
    assert len(used) == 45
    unit = gold_units(spec, substitutions=False)[0]
    assert substitute(unit, {}) is unit
