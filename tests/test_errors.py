from eval.errors import line, render, sample, unmatched

BASE = {"sector": "FULL", "event_date": "2026-07-20", "lat": None, "lon": None,
        "location_text": None, "quantity": None}  # fmt: skip
TEXT = "The enemy shelled the area."  # invented sentence


def ev(i, kind, report="r1", **over):
    return {**BASE, "id": i, "report_id": report, "event_type": kind, **over}


def test_unmatched_splits_misses_from_inventions():
    gold = [ev("g1", "shelling"), ev("g2", "air_strike")]
    preds = [ev("p1", "shelling"), ev("p2", "ground_assault"), ev("p3", "air_strike", "r2")]
    missed, invented = unmatched(preds, gold, 10, 1)
    assert [e["id"] for e in missed] == ["g2"]
    assert [e["id"] for e in invented] == ["p2", "p3"]


def test_line_reads_the_quote_from_offsets_or_from_the_record():
    with_offsets = line(ev("g", "shelling", evidence_start=4, evidence_end=9), TEXT)
    assert "> enemy" in with_offsets and "no place" in with_offsets
    no_offsets = line(ev("p", "shelling", evidence_start=None, evidence_quote="made up"), TEXT)
    assert "> made up" in no_offsets


def test_sample_is_seeded_and_capped():
    events = [ev(str(i), "other") for i in range(30)]
    assert sample(events, 10, 1) == sample(events, 10, 1) and len(sample(events, 10, 1)) == 10
    assert sample(events[:3], 10, 1) == events[:3]


def test_render_has_both_sections_and_counts():
    out = render(
        "S1", [ev("g", "shelling", evidence_start=0, evidence_end=3)], [], {"r1": TEXT}, 10, 1
    )
    assert "1 missed, 0 invented" in out and "## Invented" in out
