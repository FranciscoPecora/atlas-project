"""Per-source facts in one place (SPEC section 1 and amendment A2).

Whole-report sources (GSU, AF, RUMOD) are one FULL unit each. A2's gold units for AF
and RUMOD are not rows of SPEC 4.2: they are derived here by the amendment's rule
(the GSU dates, every 8th day from 2026-07-21; the first 3 dev, the other 12 test),
with missing dates pinned in config.yaml `gold.substitutions` like GSU's.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.collect import DATA

SOURCES = ("isw", "gsu", "af", "rumod")
FULL_SOURCES = ("gsu", "af", "rumod")
A2_SOURCES = ("af", "rumod")
A2_START = date(2026, 7, 21)
A2_REPORTS, A2_DEV = 15, 3
POST_HEADER = re.compile(r"^## (https://t\.me/\S+)", re.M)


def report_id(source: str, day: str) -> str:
    return f"{source}-{day}"


def split_report_id(rid: str) -> tuple[str, str]:
    """'rumod-2026-07-21' -> ('rumod', '2026-07-21')."""
    source, day = rid.split("-", 1)
    return source, day


def text_path(source: str, day: str, data_dir: Path = DATA) -> Path:
    return data_dir / "text" / source / f"{day}.txt"


def a2_dates() -> list[tuple[date, str]]:
    """(date, split) of A2's 15 gold reports per source, before substitution."""
    days = [A2_START + timedelta(days=8 * i) for i in range(A2_REPORTS)]
    return [(d, "dev" if i < A2_DEV else "test") for i, d in enumerate(days)]


def a2_units(source: str, cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """(report date, split) of a source's A2 gold units, substitutions applied."""
    if source not in A2_SOURCES:
        raise ValueError(f"{source} is not an A2 source")
    subs = cfg.get("gold", {}).get("substitutions", {}) or {}
    out = []
    for d, split in a2_dates():
        new = subs.get(report_id(source, d.isoformat()))
        out.append((str(new) if new else d.isoformat(), split))
    return out


def post_url_at(text: str, offset: int) -> str | None:
    """RUMOD: URL of the post whose header line comes last before `offset`."""
    url = None
    for m in POST_HEADER.finditer(text):
        if m.start() > offset:
            break
        url = m.group(1)
    return url
