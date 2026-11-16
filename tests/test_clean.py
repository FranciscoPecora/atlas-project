from src.clean import clean_gsu, clean_isw, find_cutoff, sha256_text
from src.config import load_config

GSU_PATTERN = load_config()["collect"]["gsu"]["cutoff_pattern"]

GSU_HTML = """<html><body><h1>На фронті  зафіксовано 272 боєзіткнення</h1>
<div class="single-content">
<p>Ілюстративне фото зі сторінки Генштабу</p>
<p>Про це йдеться у зведенні з оперативною інформацією станом
на 8:00 29 липня.</p>
<p>На Оріхівському напрямку   ворог атакував.</p>
</div><div class="related"><p>Читайте також</p></div></body></html>"""

ISW_HTML = """<html><body><article>
<h1>Russian Offensive Campaign Assessment, July 19, 2026</h1>
<h2>Toplines</h2><p>Top line.</p>
<h2>Russian Main Effort: Eastern Ukraine</h2>
<h3>Russian Subordinate Main Effort #2 – Oskil River</h3>
<h4>Russian objective: Cross the Oskil River</h4>
<ul><li><p>Nested paragraph.</p></li><li>Plain item.</li></ul>
</article><footer><p>Footer</p></footer></body></html>"""


def test_gsu_keeps_title_and_body_drops_photo_caption_and_page_chrome():
    text = clean_gsu(GSU_HTML)
    assert text.splitlines()[0] == "На фронті зафіксовано 272 боєзіткнення"
    assert "Ілюстративне" not in text
    assert "Читайте також" not in text
    assert "На Оріхівському напрямку ворог атакував." in text


def test_isw_marks_h2_h3_only_and_emits_each_block_once():
    text = clean_isw(ISW_HTML)
    lines = [ln for ln in text.splitlines() if ln]
    assert "## Toplines" in lines
    assert "### Russian Subordinate Main Effort #2 – Oskil River" in lines
    assert "Russian objective: Cross the Oskil River" in lines  # H4 is body text
    assert lines.count("Nested paragraph.") == 1
    assert "Plain item." in lines
    assert "Footer" not in text


def test_gsu_cutoff_is_normalised():
    assert find_cutoff(clean_gsu(GSU_HTML), "gsu", GSU_PATTERN) == "08:00 29 липня"


def test_gsu_cutoff_accepts_other_inflection_and_zero_padded_hour():
    text = "Оперативна інформація станом на 08.00 19 липня щодо вторгнення"
    assert find_cutoff(text, "gsu", GSU_PATTERN) == "08:00 19 липня"


def test_afternoon_update_is_not_a_morning_report():
    text = "Оперативна інформація станом на 16:00 19 липня"
    assert find_cutoff(text, "gsu", GSU_PATTERN) is None


def test_isw_cutoff_when_stated_and_none_otherwise():
    assert (
        find_cutoff("Data Cutoff: 2:00 pm ET on July 19.", "isw", GSU_PATTERN)
        == "2:00 pm ET on July 19"
    )
    assert find_cutoff("No cutoff here.", "isw", GSU_PATTERN) is None


def test_sha256_is_of_utf8_text():
    assert sha256_text("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
