"""Did the pre-fill steer the labels? Dev data only.

    uv run python -m src.prelabel_check

1. Anchoring: the CONTROL task (paragraphs labelled from scratch, first) is
   compared with the labels for the same paragraphs in the pre-filled FULL task.
   High agreement means the pre-fill did not change what was labelled.
2. Edits: per pre-filled dev report, how many pre-fills were kept, removed,
   and how many events were added by hand.

Events are compared on (location_text, event_type, event_date). Reads only
eval/gold/dev/ and eval/prelabel_check/, never eval/gold/test/.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from src.collect import DATA, ROOT
from src.config import load_config
from src.labels import CHECK_DIR
from src.prelabel import event_date, paragraph_spans, prefill_report

DEV = ROOT / "eval" / "gold" / "dev"
Key = tuple[str | None, str, str]


def key(record: dict) -> Key:
    return (record.get("location_text"), record["event_type"], record["event_date"])


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def agreement(a: Counter[Key], b: Counter[Key]) -> dict[str, float | int]:
    """Matches and F1 between two multisets of event keys (symmetric)."""
    matched = sum((a & b).values())
    total = sum(a.values()) + sum(b.values())
    return {"a": sum(a.values()), "b": sum(b.values()), "matched": matched,
            "f1": round(2 * matched / total, 3) if total else 1.0}  # fmt: skip


def within(records: list[dict], start: int, end: int) -> list[dict]:
    return [r for r in records if start <= r["evidence_start"] and r["evidence_end"] <= end]


def control_range(text: str, paragraphs: list[int]) -> tuple[int, int]:
    spans = paragraph_spans(text)
    return spans[paragraphs[0] - 1][0], spans[paragraphs[-1] - 1][1]


def edits(prefill_keys: Counter[Key], final_keys: Counter[Key]) -> dict[str, int]:
    kept = prefill_keys & final_keys
    return {"prefilled": sum(prefill_keys.values()), "kept": sum(kept.values()),
            "removed": sum((prefill_keys - final_keys).values()),
            "added": sum((final_keys - prefill_keys).values())}  # fmt: skip


def prefill_keys(text: str, report_date: str) -> Counter[Key]:
    day = event_date(report_date)
    return Counter((p.location_text, p.event_type, day) for p in prefill_report(text))


def main() -> None:
    cfg = load_config()["prelabel"]
    report_date = str(cfg["control_report"])
    report_id = f"gsu-{report_date}"
    control_file = CHECK_DIR / f"{report_id}__CONTROL__pass1.jsonl"
    full_file = DEV / f"{report_id}__FULL__pass1.jsonl"
    if not control_file.exists() or not full_file.exists():
        print("Anchoring check: waiting for labels. Export after labelling both")
        print(f"  {control_file.relative_to(ROOT)} and {full_file.relative_to(ROOT)}")
    else:
        text = (DATA / "text" / "gsu" / f"{report_date}.txt").read_text(encoding="utf-8")
        start, end = control_range(text, cfg["control_paragraphs"])
        control = Counter(key(r) for r in read_jsonl(control_file))
        checked = Counter(key(r) for r in within(read_jsonl(full_file), start, end))
        res = agreement(control, checked)
        verdict = "OK" if res["f1"] >= cfg["agreement_target"] else "BELOW TARGET"
        print(
            f"Anchoring check ({report_id}, paragraphs {cfg['control_paragraphs']}): "
            f"from scratch {res['a']} events, with pre-fill {res['b']}, matched "
            f"{res['matched']}, F1 {res['f1']} (target {cfg['agreement_target']}): {verdict}"
        )
        for k in sorted((control - checked).elements(), key=str):
            print(f"  only from scratch: {k}")
        for k in sorted((checked - control).elements(), key=str):
            print(f"  only with pre-fill: {k}")
    for path in sorted(DEV.glob("gsu-*__FULL__pass1.jsonl")):
        records = read_jsonl(path)
        if not any(r.get("prelabel") for r in records):
            continue
        day = records[0]["report_date"]
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        e = edits(prefill_keys(text, day), Counter(key(r) for r in records))
        print(f"Edits {path.stem.split('__')[0]}: {e}")


if __name__ == "__main__":
    main()
