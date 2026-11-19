"""Unsupported-field audit (SPEC.md 5.3): 200 records from dev-period reports not in gold.

    uv run python -m src.audit_fields dates      # list the reports the sample is drawn from
    uv run python -m src.audit_fields build      # draw the sample, translate, write the CSV
    uv run python -m src.audit_fields page       # the marking page (make mark-fields)
    uv run python -m src.audit_fields score [ANSWERS]   # rates from the page's saved file

The sample is drawn from S2 output (extraction plus deterministic checks), before
any model verifier, so one marked file gives the rate of every system: S2 is
judged on all its fields, and S3-H and S3-S on the fields their verifier kept
(records it dropped have no fields left). SPEC section 6 picks the shipped S3
variant from this comparison.

The annotator reads no Ukrainian, so every quote gets an English reading aid from
`models.translation`; the rate is therefore judged from a machine translation,
the same limit amendment A1 states for the key audit.

data/audit/fields_sample.csv holds quotes and stays local (git-ignored). The
annotator marks it on a local page (`make mark-fields`): one record per screen,
each field as a plain sentence; click the lines the quote does not support, Enter
for the next. The page saves claimline-fields-answers.json to Downloads; `score`
copies it (ids, field names, unsure flags: no text) to eval/audit/ to commit.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.collect import DATA, ROOT
from src.config import load_config
from src.labels import SPEC, gold_units
from src.verify_model import JUDGED, judged_fields

LOCAL = DATA / "audit" / "fields_sample.csv"
ANSWERS_JSON = ROOT / "eval" / "audit" / "fields_answers.json"
PAGE = DATA / "audit" / "fields_check.html"
TEMPLATE = Path(__file__).with_name("fields_page.html")
DOWNLOADS = Path.home() / "Downloads" / "claimline-fields-answers.json"
VALUE_COLUMNS = list(JUDGED)
MARK_COLUMNS = ["checked", "unsupported_fields"]


def audit_dates(spec_text: str, data_dir: Path = DATA) -> list[str]:
    """Collected GSU reports dated within the dev period that are not GSU gold units.

    The dev period runs from the first to the last dev row of SPEC 4.2.
    """
    units = gold_units(spec_text)
    dev = [u.report_date for u in units if u.split == "dev"]
    gold = {u.report_date for u in units if u.source == "gsu"}
    first, last = min(dev), max(dev)
    days = sorted(p.stem for p in (data_dir / "text" / "gsu").glob("*.txt"))
    return [
        d for d in days
        if first <= date.fromisoformat(d) <= last and date.fromisoformat(d) not in gold
    ]  # fmt: skip


def draw(records: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    """`n` records drawn without replacement, seeded, returned in (report, position) order."""
    picked = random.Random(seed).sample(records, min(n, len(records)))
    return sorted(picked, key=lambda r: (r["report_id"], r["position"]))


# Ukrainian national transliteration (2010), word-initial forms for є ї й ю я.
LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ю": "iu",
    "я": "ia", "’": "", "'": "", "ʼ": "",
}  # fmt: skip
INITIAL = {"є": "ye", "ї": "yi", "й": "y", "ю": "yu", "я": "ya"}


def latin(text: str) -> str:
    """Letter-by-letter Latin spelling of Ukrainian, so a reader can find the name in English."""
    out, start = [], True
    for ch in text:
        low = ch.lower()
        rep = (INITIAL.get(low) if start else None) or LATIN.get(low, ch)
        out.append(rep.capitalize() if ch != low and rep else rep)
        start = not ch.isalpha() and ch not in "’'ʼ"
    return "".join(out)


def rows(sample: list[dict[str, Any]], english: dict[str, str]) -> list[dict[str, str]]:
    """CSV rows: id, quote, English aid, the record's non-empty fields, two empty mark columns."""
    out = []
    for r in sample:
        fields = judged_fields(r)
        row = {
            "record_id": f"{r['report_id']}:{r['position']}",
            "report_date": r["report_date"],
            "default_date": r["default_date"],
            "quote_uk": r["evidence_quote"],
            "quote_en": english.get(r["evidence_quote"], ""),
        }
        for f in VALUE_COLUMNS:
            v = fields.get(f)
            row[f] = "" if v is None else json.dumps(v, ensure_ascii=False).strip('"')
        row["location_latin"] = latin(row["location_text"])
        out.append({**row, "checked": "", "unsupported_fields": ""})
    return out


def write_csv(path: Path, table: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)


def read_marks(path: Path) -> dict[str, set[str]]:
    """{record_id: unsupported fields} for checked rows; raises on an unknown field name."""
    marks: dict[str, set[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not row["checked"].strip():
                continue
            names = set(row["unsupported_fields"].replace(",", " ").split())
            unknown = names - set(JUDGED)
            if unknown:
                raise ValueError(f"{row['record_id']}: unknown field names {sorted(unknown)}")
            marks[row["record_id"]] = names
    return marks


def read_answers(path: Path) -> dict[str, set[str]]:
    """Marks from the page's saved file: {record_id: unsupported fields}; unsure ones left out."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("kind") != "fields":
        raise ValueError(f"{path} is not a field-check answers file")
    marks: dict[str, set[str]] = {}
    for rid, a in raw["answers"].items():
        if a.get("unsure"):
            continue
        names = set(a.get("unsupported", []))
        unknown = names - set(JUDGED)
        if unknown:
            raise ValueError(f"{rid}: unknown field names {sorted(unknown)}")
        marks[rid] = names
    return marks


def page_items(path: Path = LOCAL) -> list[dict[str, str]]:
    """The sample rows the marking page shows (read from the local CSV, no new calls)."""
    with path.open(encoding="utf-8", newline="") as f:
        table = list(csv.DictReader(f))
    return [{"id": r["record_id"], **{k: v for k, v in r.items() if k not in MARK_COLUMNS}}
            for r in table]  # fmt: skip


def render_page(items: list[dict[str, Any]], template: str) -> str:
    blob = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("/*ITEMS*/[]", blob)


def unsupported_rate(
    marks: dict[str, set[str]], kept_fields: dict[str, set[str]]
) -> tuple[int, int]:
    """(fields marked unsupported, fields judged) over the fields a system kept.

    `kept_fields` maps record_id to the non-empty fields the system output for it.
    """
    bad = total = 0
    for rid, fields in kept_fields.items():
        if rid in marks:
            total += len(fields)
            bad += len(fields & marks[rid])
    return bad, total


def bootstrap_rate(
    marks: dict[str, set[str]], kept: dict[str, set[str]], resamples: int, seed: int
) -> tuple[float, float]:
    """95% percentile interval of the rate, resampling whole reports (SPEC 5.4)."""
    by_report: dict[str, list[str]] = {}
    for rid in kept:
        if rid in marks:
            by_report.setdefault(rid.rsplit(":", 1)[0], []).append(rid)
    reports = sorted(by_report)
    rng = random.Random(seed)
    rates = []
    for _ in range(resamples):
        ids = [r for rep in rng.choices(reports, k=len(reports)) for r in by_report[rep]]
        bad = sum(len(kept[r] & marks[r]) for r in ids)
        total = sum(len(kept[r]) for r in ids)
        rates.append(bad / total if total else 0.0)
    rates.sort()
    return rates[int(0.025 * resamples)], rates[int(0.975 * resamples) - 1]


def over_removed(
    marks: dict[str, set[str]], before: dict[str, set[str]], after: dict[str, set[str]]
) -> tuple[int, int]:
    """(fields the verifier removed that the annotator judged supported, fields it removed)."""
    removed = right = 0
    for rid, fields in before.items():
        if rid not in marks:
            continue
        gone = fields - after.get(rid, set())
        removed += len(gone)
        right += len(gone & marks[rid])
    return removed - right, removed


class QuoteTranslations(BaseModel):
    english: list[str]


def translate_quotes(client: Any, models: dict[str, Any], quotes: list[str]) -> list[str]:
    """English for each quote, in order. One call per chunk; the count must match."""
    from src.translate import SYSTEM

    prompt = "Translate each numbered quote. Return the translations in the same order.\n\n"
    prompt += "\n".join(f"{i}. {q}" for i, q in enumerate(quotes, 1))
    response = client.beta.messages.parse(
        model=models["translation"],
        max_tokens=16000,
        output_config={"effort": models["translation_effort"]},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=QuoteTranslations,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"translation stopped: {response.stop_reason}")
    out = response.parsed_output.english
    if len(out) != len(quotes):
        raise ValueError(f"{len(out)} translations for {len(quotes)} quotes")
    return out


def pool(days: list[str]) -> list[dict[str, Any]]:
    """Every S2 record of the audit reports, with its position in its report's S2 list."""
    from src.extract import default_date
    from src.verify_model import s2_records

    out = []
    for day in days:
        text = (DATA / "text" / "gsu" / f"{day}.txt").read_text(encoding="utf-8")
        default = default_date({"source": "gsu", "report_date": day})
        for i, r in enumerate(s2_records(f"gsu-{day}", text)):
            out.append({**r, "report_id": f"gsu-{day}", "position": i, "report_date": day,
                        "default_date": default})  # fmt: skip
    return out


def system_fields(system: str, records: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Non-empty fields each sampled record keeps under `system` (S2, S3-H or S3-S)."""
    from src.verify_model import apply, read_verdicts

    if system == "S2":
        return {f"{r['report_id']}:{r['position']}": set(judged_fields(r)) for r in records}
    out: dict[str, set[str]] = {}
    for r in records:
        run = read_verdicts(system, r["report_id"])
        if run is None:
            raise FileNotFoundError(f"no {system} verdicts for {r['report_id']}")
        kept, _, _ = apply(r, run["verdicts"][r["position"]] or {})
        out[f"{r['report_id']}:{r['position']}"] = set(judged_fields(kept)) if kept else set()
    return out


def main(argv: list[str] | None = None) -> None:
    import anthropic
    from dotenv import load_dotenv

    from src.review import with_retries

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["dates", "build", "page", "score"])
    ap.add_argument("answers", nargs="?", type=Path, default=DOWNLOADS,
                    help="the file the page saved (score step)")  # fmt: skip
    args = ap.parse_args(argv)
    if args.step == "page":
        template = TEMPLATE.read_text(encoding="utf-8")
        PAGE.write_text(render_page(page_items(), template), encoding="utf-8")
        print(f"{len(page_items())} records -> {PAGE.relative_to(ROOT)}")
        return
    cfg = load_config()
    spec_text = SPEC.read_text(encoding="utf-8")
    days = audit_dates(spec_text)
    if args.step == "dates":
        print(len(days), "reports:", " ".join(days))
        return
    records = pool(days)
    sample = draw(records, cfg["field_audit"]["records"], cfg["field_audit"]["seed"])
    if args.step == "build":
        load_dotenv(ROOT / ".env")
        client = anthropic.Anthropic()
        quotes = list(dict.fromkeys(r["evidence_quote"] for r in sample))
        english: dict[str, str] = {}
        size = cfg["field_audit"]["translate_chunk"]
        for i in range(0, len(quotes), size):
            chunk = quotes[i : i + size]
            done = with_retries(lambda c=chunk: translate_quotes(client, cfg["models"], c))
            english.update(zip(chunk, done, strict=True))
        write_csv(LOCAL, rows(sample, english))
        print(f"{len(sample)} of {len(records)} records from {len(days)} reports, "
              f"{len(quotes)} quotes -> {LOCAL.relative_to(ROOT)}")  # fmt: skip
        return
    marks = read_answers(args.answers)
    ANSWERS_JSON.write_text(
        json.dumps(  # ids, field names and unsure flags only: no text
            json.loads(args.answers.read_text(encoding="utf-8")), indent=1
        ),
        encoding="utf-8",
    )
    print(f"{len(marks)} of {len(sample)} records judged (unsure left out); "
          f"answers copied to {ANSWERS_JSON.relative_to(ROOT)}")  # fmt: skip
    import subprocess

    from eval.score import append_results
    from src.config import config_hash

    ev = cfg["eval"]
    s2 = system_fields("S2", sample)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()  # fmt: skip
    stamp = {"commit": commit, "config_hash": config_hash(cfg), "date": date.today().isoformat(),
             "split": "dev-field-audit"}  # fmt: skip
    rows_out = []
    for system in ("S2", "S3-H", "S3-S"):
        kept = s2 if system == "S2" else system_fields(system, sample)
        bad, total = unsupported_rate(marks, kept)
        low, high = bootstrap_rate(marks, kept, ev["bootstrap_resamples"], ev["seed"])
        wrong, removed = over_removed(marks, s2, kept)
        print(f"{system}: {bad} of {total} fields unsupported = {bad / total:.2%} "
              f"[{low:.2%}, {high:.2%}]; removed {removed} fields, {wrong} of them judged "
              "supported")  # fmt: skip
        note = (
            f"200 records, seed {cfg['field_audit']['seed']}; judged from a machine "
            f"translation; resamples={ev['bootstrap_resamples']} seed={ev['seed']}"
        )
        for metric, value, n in (("unsupported_field_rate", bad / total, total),
                                 ("unsupported_field_rate_low", low, total),
                                 ("unsupported_field_rate_high", high, total),
                                 ("verifier_removed_supported", wrong, removed)):  # fmt: skip
            rows_out.append({**stamp, "system": system, "metric": metric,
                             "value": round(value, 4), "n": n, "config": note})  # fmt: skip
    append_results(rows_out)
    print(f"{len(rows_out)} rows appended to eval/results.csv")


if __name__ == "__main__":
    main()
