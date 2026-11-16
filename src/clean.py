"""Turn report HTML into the cleaned text that offsets index into.

Format of the cleaned text: one block per line, blocks separated by a blank line.
H2 and H3 headings are written as "## title" and "### title" so segment.py can
split on them. Every other block (paragraphs, list items, H4) is plain text with
whitespace collapsed to single spaces.
"""

from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup, Tag

BLOCK_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "blockquote"]
HEADING_PREFIX = {"h2": "## ", "h3": "### "}
GSU_DROP_PREFIXES = ("Ілюстративне фото", "Фото:", "Фото ")


def collapse(s: str) -> str:
    return " ".join(s.split())


def blocks_to_text(root: Tag, drop_prefixes: tuple[str, ...] = ()) -> str:
    """Render leaf block elements of root as cleaned text."""
    lines: list[str] = []
    for el in root.find_all(BLOCK_TAGS):
        if el.find(BLOCK_TAGS):  # only leaf blocks, so nothing is emitted twice
            continue
        text = collapse(el.get_text(" "))
        if not text or text.startswith(drop_prefixes):
            continue
        lines.append(HEADING_PREFIX.get(el.name, "") + text)
    return "\n\n".join(lines) + "\n"


def clean_isw(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("article") or soup.body
    if root is None:
        raise ValueError("no article or body in ISW HTML")
    return blocks_to_text(root)


def clean_gsu(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("div.single-content")
    if root is None:
        raise ValueError("no div.single-content in ArmyInform HTML")
    title = soup.find("h1")
    body = blocks_to_text(root, GSU_DROP_PREFIXES)
    return (collapse(title.get_text(" ")) + "\n\n" if title else "") + body


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


GSU_TIME = re.compile(r"станом\s+на\s+(\d{1,2})[:.](\d{2})\s+(\d{1,2}\s+\w+)")
ISW_CUTOFF = re.compile(r"Data [Cc]ut-?off:?\s*([^\n.]{1,60})")


def find_cutoff(text: str, source: str, gsu_pattern: str) -> str | None:
    """Return the data cutoff as stated in the text, or None."""
    if source == "gsu":
        m = re.search(gsu_pattern, text)
        if not m:
            return None
        t = GSU_TIME.search(text, m.start())
        return f"{int(t.group(1)):02d}:{t.group(2)} {t.group(3)}" if t else None
    m = ISW_CUTOFF.search(text)
    return collapse(m.group(1)) if m else None
