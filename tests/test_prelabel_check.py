from collections import Counter

from src.prelabel_check import agreement, control_range, edits, key, within

A = ("Ясного", "ground_assault", "2026-08-05")
B = ("Кам’янки", "ground_assault", "2026-08-05")
C = ("Кам’янки", "shelling", "2026-08-05")


def test_agreement_is_symmetric_f1_on_event_keys():
    res = agreement(Counter([A, B]), Counter([A, C]))
    assert res == {"a": 2, "b": 2, "matched": 1, "f1": 0.5}
    assert agreement(Counter(), Counter())["f1"] == 1.0


def test_edits_count_kept_removed_added():
    assert edits(Counter([A, B]), Counter([A, C])) == {
        "prefilled": 2,
        "kept": 1,
        "removed": 1,
        "added": 1,
    }


def test_within_and_control_range():
    text = "Заголовок\n\nПерший абзац.\n\nДругий абзац.\n"
    start, end = control_range(text, [2, 3])
    assert text[start:end] == "Перший абзац.\n\nДругий абзац."
    recs = [
        {"evidence_start": start, "evidence_end": start + 6},
        {"evidence_start": 0, "evidence_end": 5},
    ]
    assert within(recs, start, end) == recs[:1]


def test_key_uses_location_type_and_date():
    rec = {"location_text": "Ясного", "event_type": "ground_assault", "event_date": "2026-08-05"}
    assert key(rec) == A
