from datetime import date
from types import SimpleNamespace

import pytest

from src.labels import SPEC, gold_units
from src.translate import (
    PlaceName,
    RefusedTestSplit,
    TranslatedParagraph,
    Translation,
    build_prompt,
    is_test_report,
    load_translation,
    main,
    paragraphs,
    preview,
    problems,
    render_english,
    render_places,
    translate,
    write_translation,
)

TEXT = (
    "Заголовок звіту\n\nВорог атакував біля Покровська 14 разів.\n\nНа Куп’янському напрямку тихо."
)
MODELS = {"translation": "model-from-config", "translation_effort": "medium"}


def good() -> Translation:
    return Translation(
        paragraphs=[
            TranslatedParagraph(index=1, english="Report title", places=[]),
            TranslatedParagraph(
                index=2,
                english="The enemy attacked near Pokrovsk 14 times.",
                places=[PlaceName(source="Покровська", english="Pokrovsk")],
            ),
            TranslatedParagraph(index=3, english="Quiet on the Kupiansk direction.", places=[]),
        ]
    )


class FakeClient:
    def __init__(self, result: Translation | None, stop: str = "end_turn") -> None:
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))
        self._result, self._stop = result, stop

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self._stop, parsed_output=self._result)


def test_paragraphs_split_on_blank_lines():
    assert len(paragraphs(TEXT)) == 3
    assert paragraphs("a\n\n\n\nb\n") == ["a", "b"]


def test_prompt_numbers_every_paragraph():
    prompt = build_prompt(paragraphs(TEXT))
    assert "[1] Заголовок звіту" in prompt and "[3] На Куп" in prompt
    assert "3 numbered paragraphs" in prompt


def test_problems_catches_invented_place_and_wrong_count():
    paras = paragraphs(TEXT)
    assert problems(good(), paras) == []
    bad = good()
    bad.paragraphs[1].places.append(PlaceName(source="Харків", english="Kharkiv"))
    assert problems(bad, paras) == ["[2] place 'Харків' is not in the paragraph"]
    short = Translation(paragraphs=good().paragraphs[:2])
    assert "do not match" in problems(short, paras)[0]


def test_translate_uses_config_model_and_returns_checked_result():
    client = FakeClient(good())
    result = translate(client, MODELS, TEXT)
    assert result == good()
    (call,) = client.calls
    assert call["model"] == "model-from-config"
    assert call["output_config"] == {"effort": "medium"}
    assert call["output_format"] is Translation


def test_translate_raises_on_refusal_or_failed_check():
    with pytest.raises(RuntimeError, match="refusal"):
        translate(FakeClient(None, stop="refusal"), MODELS, TEXT)
    bad = good()
    bad.paragraphs[2].places.append(PlaceName(source="Ізюм", english="Izium"))
    with pytest.raises(ValueError, match="Ізюм"):
        translate(FakeClient(bad), MODELS, TEXT)


def test_rendering_shows_ukrainian_start_and_place_list():
    paras = paragraphs(TEXT)
    english = render_english(good(), paras)
    assert "[2] starts: Ворог атакував біля Покровська 14 разів.\n" in english
    assert "The enemy attacked near Pokrovsk 14 times." in english
    assert render_places(good()) == "Покровська = Pokrovsk"
    assert preview("один два три чотири п'ять шість сім", 3) == "один два три …"


def test_round_trip_through_json(tmp_path):
    write_translation("2026-07-21", good(), paragraphs(TEXT), "m", tmp_path)
    rec = load_translation("2026-07-21", tmp_path)
    assert rec["places"] == "Покровська = Pokrovsk" and rec["model"] == "m"
    assert load_translation("2026-07-22", tmp_path) is None


def test_test_split_reports_are_refused(tmp_path, monkeypatch):
    spec = SPEC.read_text(encoding="utf-8")
    test_day = next(u for u in gold_units(spec) if u.source == "gsu" and u.split == "test")
    dev_day = next(u for u in gold_units(spec) if u.source == "gsu" and u.split == "dev")
    assert is_test_report(test_day.report_date, "gsu", spec)
    assert not is_test_report(dev_day.report_date, "gsu", spec)
    assert not is_test_report(date(2026, 7, 20), "gsu", spec)  # not a gold report at all

    gsu = tmp_path / "gsu"
    gsu.mkdir()
    path = gsu / f"{test_day.report_date.isoformat()}.txt"
    path.write_text(TEXT, encoding="utf-8")
    monkeypatch.setattr("src.translate.anthropic.Anthropic", lambda: FakeClient(good()))
    with pytest.raises(RefusedTestSplit):
        main([str(path)])
