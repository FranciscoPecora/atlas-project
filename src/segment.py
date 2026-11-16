"""Split a cleaned report into sector units (SPEC.md section 3).

uv run python -m src.segment data/text/isw/2026-07-19.txt
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Order matters: first match wins (SPEC.md section 3).
SECTOR_RULES: list[tuple[tuple[str, ...], str]] = [
    (("toplines", "key takeaways"), "SUMMARY"),
    (("belarus",), "BELARUS"),
    (("russian federation",), "RU_INTERIOR"),
    (("northern axis",), "NORTH"),
    (("oskil",), "OSKIL"),
    (("kharkiv",), "KHARKIV"),
    (("donetsk", "fortress belt", "dnipropetrovsk"), "DONETSK"),
    (("southern axis",), "SOUTH"),
    (("air, missile", "drone campaign"), "AIR"),
]
SAMPLED_SECTORS = ("AIR", "DONETSK", "KHARKIV", "NORTH", "OSKIL", "RU_INTERIOR", "SOUTH")
HEADING = re.compile(r"^(#{2,3}) (.+)$", re.MULTILINE)


class UnmappedHeading(ValueError):
    pass


@dataclass(frozen=True)
class Section:
    sector: str
    headings: tuple[str, ...]
    start: int  # offset into the cleaned report text
    end: int  # exclusive


def sector_for(heading: str) -> str:
    h = heading.lower()
    for keywords, sector in SECTOR_RULES:
        if any(k in h for k in keywords):
            return sector
    raise UnmappedHeading(heading)


def _raw_sections(text: str) -> list[tuple[str | None, int, int, bool]]:
    """(heading or None for preamble, start, end, has_body) in text order."""
    marks = list(HEADING.finditer(text))
    out: list[tuple[str | None, int, int, bool]] = []
    first = marks[0].start() if marks else len(text)
    if text[:first].strip():
        out.append((None, 0, first, True))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end() : end]
        out.append((m.group(2).strip(), m.start(), end, bool(body.strip())))
    return out


def segment(text: str, source: str) -> list[Section]:
    """Return sector units in text order. GSU reports are one FULL unit."""
    if source == "gsu":
        return [Section("FULL", (), 0, len(text))]
    units: list[Section] = []
    for heading, start, end, has_body in _raw_sections(text):
        if heading is None:
            sector, names = "SUMMARY", ()
        elif not has_body:
            continue  # container heading: no sector (SPEC.md section 3)
        else:
            sector, names = sector_for(heading), (heading,)
        units.append(Section(sector, names, start, end))
    return _absorb_containers(units, text)


def _absorb_containers(units: list[Section], text: str) -> list[Section]:
    """Skipped container headings leave gaps; give each gap to the unit after it.

    Then consecutive units of the same sector are merged again, so a sector split
    only by a container heading becomes one unit.
    """
    fixed: list[Section] = []
    cursor = 0
    for u in units:
        fixed.append(Section(u.sector, u.headings, cursor, u.end))
        cursor = u.end
    merged: list[Section] = []
    for u in fixed:
        if merged and merged[-1].sector == u.sector:
            prev = merged.pop()
            merged.append(Section(u.sector, prev.headings + u.headings, prev.start, u.end))
        else:
            merged.append(u)
    if merged:
        last = merged[-1]
        merged[-1] = Section(last.sector, last.headings, last.start, len(text))
    return merged


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    for p in args:
        path = Path(p)
        source = path.parent.name
        text = path.read_text(encoding="utf-8")
        print(f"== {path}")
        for s in segment(text, source):
            label = " | ".join(s.headings) or "(preamble)"
            print(f"  {s.sector:12} {s.start:>7}-{s.end:<7} {label}")


if __name__ == "__main__":
    main()
