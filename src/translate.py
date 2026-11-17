"""English reading aid for Ukrainian General Staff reports, dev units only.

    uv run python -m src.translate data/text/gsu/2026-07-21.txt [...] [--force]

The annotator cannot read Ukrainian. This writes, per report, a paragraph-by-
paragraph English translation and a list of place names, to
data/text/gsu_en/{date}.json (git-ignored: it is derived source text). The
Label Studio task shows it next to the Ukrainian, which stays the text that is
labelled, so gold offsets still point into the original.

SPEC.md section 4: test sections are never labelled from model output. A
translation is model output, so this refuses any report in the test split.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.collect import DATA, ROOT
from src.config import load_config
from src.labels import SPEC, gold_units

OUT_DIR = DATA / "text" / "gsu_en"
PREVIEW_WORDS = 6

SYSTEM = (
    "You translate Ukrainian military situation reports into plain English for a "
    "research annotator who reads no Ukrainian. Translate faithfully: keep every "
    "number, place, unit, weapon and attribution ('the enemy', 'our defenders'). "
    "Do not summarise, merge or drop sentences, and add nothing. Transliterate "
    "place names in their usual English spelling (Pokrovsk, Kupiansk)."
)


class PlaceName(BaseModel):
    source: str = Field(description="The place name exactly as written in the paragraph")
    english: str = Field(description="Usual English spelling, nominative case")


class TranslatedParagraph(BaseModel):
    index: int = Field(description="The paragraph number given in the input")
    english: str
    places: list[PlaceName]


class Translation(BaseModel):
    paragraphs: list[TranslatedParagraph]


class RefusedTestSplit(RuntimeError):
    pass


def paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, as src/clean.py writes them."""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def build_prompt(paras: list[str]) -> str:
    numbered = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(paras, start=1))
    return (
        f"Translate each of the {len(paras)} numbered paragraphs below. Return one "
        "entry per paragraph with the same number, in order. For each paragraph, "
        "list every settlement, district, oblast or river it names, copied exactly "
        "as written (keep the Ukrainian case ending), with its English name.\n\n"
        f"{numbered}"
    )


def problems(result: Translation, paras: list[str]) -> list[str]:
    """Code-side checks: one entry per paragraph, place names really in the text."""
    found: list[str] = []
    indices = [p.index for p in result.paragraphs]
    if indices != list(range(1, len(paras) + 1)):
        found.append(f"paragraph numbers {indices} do not match 1..{len(paras)}")
        return found
    for p in result.paragraphs:
        for place in p.places:
            if place.source not in paras[p.index - 1]:
                found.append(f"[{p.index}] place {place.source!r} is not in the paragraph")
    return found


def is_test_report(report_date: date, source: str, spec_text: str) -> bool:
    return any(
        u.report_date == report_date and u.source == source and u.split == "test"
        for u in gold_units(spec_text)
    )


def translate(client: Any, models: dict[str, Any], text: str) -> Translation:
    paras = paragraphs(text)
    response = client.beta.messages.parse(
        model=models["translation"],
        max_tokens=16000,
        output_config={"effort": models["translation_effort"]},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(paras)}],
        output_format=Translation,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"translation stopped: {response.stop_reason}")
    result = response.parsed_output
    issues = problems(result, paras)
    if issues:
        raise ValueError("translation failed checks: " + "; ".join(issues))
    return result


def preview(paragraph: str, words: int = PREVIEW_WORDS) -> str:
    """The paragraph's first words, so the annotator can match it by sight."""
    head = paragraph.split()
    return " ".join(head[:words]) + (" …" if len(head) > words else "")


def render_english(result: Translation, paras: list[str]) -> str:
    return "\n\n".join(
        f"[{p.index}] starts: {preview(paras[p.index - 1])}\n{p.english}" for p in result.paragraphs
    )


def render_places(result: Translation) -> str:
    seen: dict[str, str] = {}
    for p in result.paragraphs:
        for place in p.places:
            seen.setdefault(place.source, place.english)
    return "\n".join(f"{src} = {en}" for src, en in seen.items())


def load_translation(report_date: str, out_dir: Path = OUT_DIR) -> dict[str, str] | None:
    path = out_dir / f"{report_date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_translation(
    report_date: str, result: Translation, paras: list[str], model: str, out_dir: Path = OUT_DIR
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report_date}.json"
    record = {
        "report_date": report_date,
        "model": model,
        "translation": render_english(result, paras),
        "places": render_places(result),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--force", action="store_true", help="translate again if a file exists")
    args = ap.parse_args(argv)

    load_dotenv(ROOT / ".env")
    models = load_config()["models"]
    spec_text = SPEC.read_text(encoding="utf-8")
    client = anthropic.Anthropic()
    for path in args.files:
        day = date.fromisoformat(path.stem)
        if path.parent.name != "gsu":
            sys.exit(f"{path}: only General Staff (gsu) reports are translated")
        if is_test_report(day, "gsu", spec_text):
            raise RefusedTestSplit(
                f"{path}: test-split report; SPEC.md section 4 forbids labelling it from "
                "model output"
            )
        if load_translation(path.stem) and not args.force:
            print(f"{path.stem}: already translated, skipped (use --force)")
            continue
        paras = paragraphs(path.read_text(encoding="utf-8"))
        result = translate(client, models, path.read_text(encoding="utf-8"))
        out = write_translation(path.stem, result, paras, models["translation"])
        n_places = len(render_places(result).splitlines())
        print(f"{path.stem}: {len(paras)} paragraphs, {n_places} place names -> {out}")


if __name__ == "__main__":
    main()
