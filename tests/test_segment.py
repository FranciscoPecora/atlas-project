import pytest

from src.segment import SAMPLED_SECTORS, UnmappedHeading, sector_for, segment

# Heading sequences seen in ISW reports of 2026-07-19 and 2026-11-15.
# Bodies are placeholders; "" marks a container heading with no body.
JULY = [
    ("##", "Toplines", "Body."),
    ("##", "Key Takeaways", "Body."),
    ("##", "Ukrainian Operations in the Russian Federation", "Body."),
    ("##", "Russian Supporting Effort: Northern Axis", "Body."),
    ("##", "Russian Main Effort: Eastern Ukraine", ""),
    ("###", "Russian Subordinate Main Effort #1 – Kharkiv Oblast", "Body."),
    ("###", "Russian Subordinate Main Effort #2 – Oskil River", "Body."),
    ("###", "Russian Subordinate Main Effort #3 – Donetsk Oblast", "Body."),
    ("##", "Russian Supporting Effort: Southern Axis", "Body."),
    ("##", "Russian Air, Missile, and Drone Campaign", "Body."),
    ("##", "Significant Activity in Belarus", "Body."),
]
NOVEMBER = [
    ("##", "Toplines", "Body."),
    ("##", "Key Takeaways", "Body."),
    ("##", "Ukrainian Operations in the Russian Federation", "Body."),
    ("##", "Russian Supporting Effort: Northern Axis", "Body."),
    ("##", "Russian Supporting Effort: Kharkiv Oblast", "Body."),
    ("##", "Russian Supporting Effort: Oskil River", "Body."),
    (
        "##",
        "Russian Main Effort: Capture Ukraine’s Fortress Belt and complete the seizure of "
        "Donetsk Oblast",
        "",
    ),
    (
        "###",
        "Russian Subordinate Main Effort #1 – Encircle the Fortress Belt from the northwest",
        "B.",
    ),
    (
        "###",
        "Russian Subordinate Main Effort #2 – Advance on the Fortress Belt from the east",
        "B.",
    ),
    (
        "###",
        "Russian Subordinate Main Effort #3 – Advance on the Fortress Belt from the south",
        "B.",
    ),
    (
        "###",
        "Russian Subordinate Main Effort #4 – Encircle the Fortress Belt from the southwest",
        "B.",
    ),
    ("##", "Russian Supporting Effort: Advance into Dnipropetrovsk Oblast", "Body."),
    ("##", "Russian Supporting Effort: Southern Axis", "Body."),
    ("##", "Russian Air, Missile, and Drone Campaign", "Body."),
    ("##", "Significant Activity in Belarus", "Body."),
]


def build(spec: list[tuple[str, str, str]], preamble: str = "Title\n\nMay 1, 2026\n\n") -> str:
    parts = [preamble]
    for hashes, title, body in spec:
        parts.append(f"{hashes} {title}\n\n")
        if body:
            parts.append(f"{body}\n\n")
    return "".join(parts)


EXPECTED_ORDER = [
    "SUMMARY",
    "RU_INTERIOR",
    "NORTH",
    "KHARKIV",
    "OSKIL",
    "DONETSK",
    "SOUTH",
    "AIR",
    "BELARUS",
]


@pytest.mark.parametrize("spec", [JULY, NOVEMBER], ids=["july", "november"])
def test_both_heading_layouts_map_to_the_same_sectors(spec):
    text = build(spec)
    sections = segment(text, "isw")
    assert [s.sector for s in sections] == EXPECTED_ORDER
    assert set(SAMPLED_SECTORS) <= {s.sector for s in sections}


@pytest.mark.parametrize("spec", [JULY, NOVEMBER], ids=["july", "november"])
def test_sections_tile_the_text_without_gaps(spec):
    text = build(spec)
    sections = segment(text, "isw")
    assert sections[0].start == 0
    assert sections[-1].end == len(text)
    for a, b in zip(sections, sections[1:], strict=False):
        assert a.end == b.start


def test_november_donetsk_unit_merges_five_headings():
    sections = segment(build(NOVEMBER), "isw")
    donetsk = next(s for s in sections if s.sector == "DONETSK")
    assert len(donetsk.headings) == 5  # 4 Fortress Belt H3s + Dnipropetrovsk; container skipped


def test_container_heading_is_inside_the_following_unit():
    text = build(JULY)
    sections = segment(text, "isw")
    kharkiv = next(s for s in sections if s.sector == "KHARKIV")
    assert "Eastern Ukraine" in text[kharkiv.start : kharkiv.end]


def test_unknown_heading_with_body_raises():
    with pytest.raises(UnmappedHeading):
        segment(build([("##", "Something New", "Body.")]), "isw")


def test_gsu_is_one_full_unit():
    text = "Заголовок\n\nТекст.\n"
    assert [(s.sector, s.start, s.end) for s in segment(text, "gsu")] == [("FULL", 0, len(text))]


@pytest.mark.parametrize(
    "heading,sector",
    [
        ("Russian Subordinate Main Effort #2 – Oskil River", "OSKIL"),
        ("Russian Supporting Effort: Kharkiv Oblast", "KHARKIV"),
        ("KEY TAKEAWAYS", "SUMMARY"),
    ],
)
def test_sector_rules_are_ordered_and_case_insensitive(heading, sector):
    assert sector_for(heading) == sector
