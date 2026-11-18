from src.verify_det import (
    LOCATION_NOT_IN_QUOTE,
    QUANTITY_NOT_IN_QUOTE,
    QUOTE_MISSING,
    check,
    find_quote,
    has_location,
    has_quantity,
    normalise,
    verify,
)

# Invented sentences, never real report text.
TEXT = "Title\n\nThe enemy   attacked “near” Kup’iansk – twice.\n\nThe enemy attacked again."


def test_normalise_folds_spaces_quotes_apostrophes_and_dashes():
    norm, spans = normalise("a \n b «c» d’e — f")
    assert norm == 'a b "c" d\'e - f'
    assert len(spans) == len(norm)


def test_normalise_composes_combining_marks():
    norm, spans = normalise("ïx")  # i + combining diaeresis
    assert norm == "ïx" and spans == [(0, 2), (2, 3)]


def test_find_quote_returns_offsets_into_the_original_text():
    start, end, ambiguous = find_quote('attacked "near" Kup\'iansk - twice', TEXT)
    assert TEXT[start:end] == "attacked “near” Kup’iansk – twice"
    assert ambiguous is False


def test_find_quote_flags_a_repeated_quote_and_takes_the_first():
    start, _, ambiguous = find_quote("The enemy attacked", TEXT)
    assert start == TEXT.index("The enemy") and ambiguous is True


def test_find_quote_missing_or_empty():
    assert find_quote("The enemy retreated", TEXT) is None
    assert find_quote("   ", TEXT) is None


def test_has_location_after_normalisation():
    assert has_location("near Kup’iansk", "Kup'iansk")
    assert not has_location("near Kup’iansk", "Lyman")


def test_has_quantity_digits_and_number_words():
    assert has_quantity("lost 10 408 soldiers", 10408)
    assert has_quantity("lost 1,200 soldiers", 1200)
    assert has_quantity("attacked twelve times", 12)
    assert has_quantity("ворог тричі атакував", 3)
    assert not has_quantity("attacked twelve times", 13)
    assert not has_quantity("attacked several times", 3)


def event(**over):
    base = {"evidence_quote": "The enemy attacked again.", "location_text": None, "quantity": None}
    return {**base, **over}


def test_check_accepts_and_adds_offsets():
    record, reason = check(event(), TEXT)
    assert reason is None
    assert TEXT[record["evidence_start"] : record["evidence_end"]] == "The enemy attacked again."
    assert record["ambiguous_offset"] is False


def test_check_rejects_with_one_reason_each():
    assert check(event(evidence_quote="Not in the text"), TEXT) == (None, QUOTE_MISSING)
    assert check(event(location_text="Lyman"), TEXT) == (None, LOCATION_NOT_IN_QUOTE)
    assert check(event(quantity=4), TEXT) == (None, QUANTITY_NOT_IN_QUOTE)


def test_verify_counts_rejections_by_reason():
    kept, rejected = verify([event(), event(quantity=4), event(evidence_quote="x y z")], TEXT)
    assert len(kept) == 1
    assert rejected == {QUANTITY_NOT_IN_QUOTE: 1, QUOTE_MISSING: 1}
