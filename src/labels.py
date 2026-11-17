"""Label Studio tasks in, gold labels out.

    uv run python -m src.labels tasks            # write data/labelstudio/tasks.json
    uv run python -m src.labels tasks --pilot    # dev units only
    uv run python -m src.labels export EXPORT.json   # write eval/gold/{dev,test}/

Gold units come from the rotation table in SPEC.md section 4.2, never from a
list typed here. Exported gold files hold offsets into the report text and its
SHA-256, not the quoted text, so they can be committed.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.collect import DATA, ROOT, read_manifest
from src.config import load_config
from src.schema import ExtractedEvent
from src.segment import segment

SPEC = ROOT / "SPEC.md"
TASKS = DATA / "labelstudio" / "tasks.json"
GOLD = ROOT / "eval" / "gold"
CHECK_DIR = ROOT / "eval" / "prelabel_check"  # control-task labels; not gold
# Seeded permutation from SPEC.md section 4.1, used for the absent-sector fallback.
PERM = ["AIR", "RU_INTERIOR", "OSKIL", "KHARKIV", "NORTH", "SOUTH", "DONETSK"]
ROW = re.compile(
    r"^\| (\d+) \| (\d{4}-\d{2}-\d{2}) \| (ISW|GSU) \| ([A-Z_, ]+?) \| (dev|test) \|$", re.M
)
LIST_FIELDS = ("units", "equipment")
TEXT_FIELDS = ("claim_source", "location_text", "event_date")
CHOICE_FIELDS = ("event_type", "epistemic_status", "actor", "target", "geo_precision")


@dataclass(frozen=True)
class GoldUnit:
    row: int
    report_date: date
    source: str  # "isw" or "gsu"
    sectors: tuple[str, ...]
    split: str

    @property
    def report_id(self) -> str:
        return f"{self.source}-{self.report_date.isoformat()}"


def gold_units(spec_text: str) -> list[GoldUnit]:
    units = [
        GoldUnit(
            row=int(m.group(1)),
            report_date=date.fromisoformat(m.group(2)),
            source=m.group(3).lower(),
            sectors=tuple(s.strip() for s in m.group(4).split(",")),
            split=m.group(5),
        )
        for m in ROW.finditer(spec_text)
    ]
    if len(units) != 45:
        raise ValueError(f"expected 45 rotation rows in SPEC.md, found {len(units)}")
    return units


def resolve_sectors(drawn: tuple[str, ...], available: set[str]) -> list[str]:
    """Replace each absent drawn sector with the next sector in PERM order (SPEC 4.1)."""
    chosen: list[str] = []
    for sector in drawn:
        if sector in available and sector not in chosen:
            chosen.append(sector)
            continue
        start = PERM.index(sector)
        for k in range(1, len(PERM) + 1):
            alt = PERM[(start + k) % len(PERM)]
            if alt in available and alt not in chosen and alt not in drawn:
                chosen.append(alt)
                break
    return chosen


def tasks_for_unit(unit: GoldUnit, text: str, sha: str, url: str) -> list[dict[str, Any]]:
    sections = segment(text, unit.source)
    by_sector = {s.sector: s for s in sections}
    wanted = ["FULL"] if unit.source == "gsu" else resolve_sectors(unit.sectors, set(by_sector))
    tasks = []
    for sector in wanted:
        s = by_sector[sector]
        tasks.append(
            {
                "data": {
                    "text": text[s.start : s.end],
                    "unit_start": s.start,
                    "report_id": unit.report_id,
                    "source": unit.source,
                    "report_date": unit.report_date.isoformat(),
                    "sector": sector,
                    "split": unit.split,
                    "text_sha256": sha,
                    "source_url": url,
                }
            }
        )
    return tasks


def make_tasks(units: list[GoldUnit], data_dir: Path = DATA) -> tuple[list[dict], list[str]]:
    from src.translate import load_translation  # local: src.translate imports this module

    manifest = {(r["date"], r["source"]): r for r in read_manifest(data_dir / "manifest.csv")}
    tasks: list[dict] = []
    missing: list[str] = []
    for u in units:
        m = manifest.get((u.report_date.isoformat(), u.source))
        path = data_dir / "text" / u.source / f"{u.report_date.isoformat()}.txt"
        if not m or m["status"] != "ok" or not path.exists():
            missing.append(u.report_id)
            continue
        text = path.read_text(encoding="utf-8")
        unit_tasks = tasks_for_unit(u, text, m["sha256"], m["url"])
        reading_aid = load_translation(u.report_date.isoformat(), data_dir / "text" / "gsu_en")
        tasks += [attach_prefill(attach_reading_aid(t, reading_aid), text) for t in unit_tasks]
    return tasks, missing


def attach_prefill(task: dict[str, Any], report_text: str) -> dict[str, Any]:
    """Rule-based pre-fill for GSU dev tasks only. Test tasks start empty (SPEC 4)."""
    from src.prelabel import VERSION, prefill_report, to_prediction

    data = task["data"]
    data["prelabel"] = ""
    if data["source"] == "gsu" and data["split"] == "dev" and data["sector"] == "FULL":
        task["predictions"] = [to_prediction(prefill_report(report_text), data)]
        data["prelabel"] = VERSION
    return task


def control_task(full_task: dict[str, Any], paragraphs: list[int]) -> dict[str, Any]:
    """The anchoring check: chosen paragraphs of a GSU dev report, no pre-fill, labelled
    before the full pre-filled task. Its labels go to eval/prelabel_check/, not gold."""
    from src.prelabel import paragraph_spans

    data = full_task["data"]
    if data["split"] != "dev" or data["sector"] != "FULL":
        raise ValueError("a control task is cut from a GSU dev FULL task only")
    spans = paragraph_spans(data["text"])
    start, end = spans[paragraphs[0] - 1][0], spans[paragraphs[-1] - 1][1]
    return {
        "data": {
            **data,
            "text": data["text"][start:end],
            "unit_start": data["unit_start"] + start,
            "sector": "CONTROL",
            "purpose": "control",
            "prelabel": "",  # same reading aid as the full task; only the pre-fill differs
        }
    }


def with_control(tasks: list[dict[str, Any]], report_id: str, paragraphs: list[int]) -> list[dict]:
    """Put the control task first, so it is labelled before any pre-fill is seen."""
    full = next(t for t in tasks if t["data"]["report_id"] == report_id)
    return [control_task(full, paragraphs), *tasks]


NO_AID = "(no translation: English source, or test-split report)"


def attach_reading_aid(task: dict[str, Any], record: dict[str, str] | None) -> dict[str, Any]:
    """Add the English reading aid to a GSU dev task. Never for test units (SPEC 4)."""
    data = task["data"]
    usable = record is not None and data["source"] == "gsu" and data["split"] == "dev"
    data["translation"] = record["translation"] if usable else NO_AID
    data["places"] = record["places"] if usable else ""
    return task


def _regions(result: list[dict]) -> tuple[dict[str, dict], dict[str, Any]]:
    """Group per-region results by region id; collect task-level fields separately."""
    regions: dict[str, dict] = defaultdict(dict)
    task_level: dict[str, Any] = {}
    for item in result:
        name, value = item["from_name"], item["value"]
        per_region = "start" in value
        if item["type"] == "labels":
            regions[item["id"]]["span"] = value
            continue
        if item["type"] == "choices":
            v: Any = value["choices"][0]
        elif item["type"] == "textarea":
            v = "\n".join(value["text"]).strip()
        elif item["type"] == "number":
            v = value["number"]
        else:
            continue
        if per_region:
            regions[item["id"]][name] = v
        else:
            task_level[name] = v
    return regions, task_level


def region_to_record(region: dict, data: dict) -> dict[str, Any]:
    span = region["span"]
    quote = data["text"][span["start"] : span["end"]]
    fields: dict[str, Any] = {"evidence_quote": quote}
    for f in CHOICE_FIELDS + TEXT_FIELDS:
        v = region.get(f)
        fields[f] = v if v not in ("", None) else None
    fields["geo_precision"] = int(fields["geo_precision"]) if fields["geo_precision"] else None
    fields["quantity"] = region.get("quantity")
    for f in LIST_FIELDS:
        lines = [ln.strip() for ln in (region.get(f) or "").splitlines() if ln.strip()]
        fields[f] = [{"name": ln} for ln in lines] if f == "units" else lines
    event = ExtractedEvent.model_validate(fields)  # same enums and ranges as the model
    record = event.model_dump(mode="json", exclude={"evidence_quote"})
    record.update(
        report_id=data["report_id"],
        source=data["source"],
        report_date=data["report_date"],
        sector=data["sector"],
        evidence_start=data["unit_start"] + span["start"],
        evidence_end=data["unit_start"] + span["end"],
        text_sha256=data["text_sha256"],
        source_url=data["source_url"],
    )
    return record


def export(
    ls_export: list[dict], gold_dir: Path = GOLD, check_dir: Path = CHECK_DIR
) -> dict[str, int]:
    """Write one JSONL file per (unit, pass) into the split given by the task. Returns counts."""
    counts: dict[str, int] = defaultdict(int)
    for task in ls_export:
        data = task["data"]
        for ann in task.get("annotations", []):
            if ann.get("was_cancelled"):
                continue
            regions, task_level = _regions(ann["result"])
            n_pass = int(task_level.get("pass", 1))
            records = [region_to_record(r, data) for r in regions.values() if "span" in r]
            for r in records:
                r["annotation_pass"] = n_pass
                r["minutes"] = task_level.get("minutes")
                r["prelabel"] = data.get("prelabel") or None
            records.sort(key=lambda r: (r["evidence_start"], r["evidence_end"]))
            folder = check_dir if data.get("purpose") == "control" else gold_dir / data["split"]
            out = folder / f"{data['report_id']}__{data['sector']}__pass{n_pass}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
            )
            counts["control" if data.get("purpose") == "control" else data["split"]] += len(records)
    return dict(counts)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tasks")
    t.add_argument("--pilot", action="store_true", help="dev units only")
    e = sub.add_parser("export")
    e.add_argument("path", type=Path, help="Label Studio JSON export")
    args = ap.parse_args(argv)

    if args.cmd == "tasks":
        units = gold_units(SPEC.read_text(encoding="utf-8"))
        if args.pilot:
            units = [u for u in units if u.split == "dev"]
        tasks, missing = make_tasks(units)
        pre = load_config()["prelabel"]
        control_id = f"gsu-{pre['control_report']}"
        if any(t["data"]["report_id"] == control_id for t in tasks):
            tasks = with_control(tasks, control_id, pre["control_paragraphs"])
        TASKS.parent.mkdir(parents=True, exist_ok=True)
        TASKS.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(tasks)} tasks -> {TASKS.relative_to(ROOT)}")
        print(f"{len(missing)} gold reports not collected yet: {', '.join(missing) or '-'}")
    else:
        counts = export(json.loads(args.path.read_text(encoding="utf-8")))
        print("events exported per split:", counts)


if __name__ == "__main__":
    main()
