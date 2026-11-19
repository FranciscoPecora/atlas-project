"""Collector paths added by SPEC amendment A2: Air Force (af) and Russian MoD (rumod)."""

from datetime import date

from src import sources
from src.clean import clean_telegram_post, find_cutoff
from src.collect import Collector, body_pattern, claim_posts, parse_channel_page, rumod_report
from src.config import load_config
from tests.test_collect import BASE, article, make_fetcher

CFG = load_config()
TG = "https://t.me"


def tg_post(pid: int, utc: str, text_html: str) -> str:
    return (
        f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" '
        f'data-post="mod_russia/{pid}"><div class="tgme_widget_message_text js-message_text" '
        f'dir="auto">{text_html}</div><a class="tgme_widget_message_date"><time '
        f'datetime="{utc}"></time></a></div></div>'
    )


def test_af_body_pattern_needs_night_and_air_force():
    pat = body_pattern(CFG, "af")
    import re

    ok = "У ніч на 3 серпня противник атакував.\n\nПро це повідомили Повітряні Сили ЗСУ."
    assert re.search(pat, ok)
    assert not re.search(pat, "Повітряні сили отримали нові літаки.")
    assert not re.search(pat, "У ніч на 3 серпня ворог атакував Харків.")


def test_collect_af_picks_the_air_force_report(tmp_path):
    day = date(2026, 8, 3)
    other = f"{BASE}/2026/08/03/raket-potribni-tut/"
    report = f"{BASE}/2026/08/03/zneshkodzheni-163-zi-181-udarnyh-bpla-voroga-povitryani-syly/"
    sitemap = f"<urlset><loc>{other}</loc><loc>{report}</loc></urlset>"
    routes = {
        f"{BASE}/robots.txt": (200, ""),
        f"{BASE}/sitemap-posttype-post.202608.xml": (200, sitemap),
        other: (200, article("Президент заслухав доповідь.")),
        report: (200, article("У ніч на 3 серпня противник атакував 181 БПЛА. Повітряні сили.")),
    }
    row = Collector(CFG, make_fetcher(routes), data_dir=tmp_path).collect(["af"][0], [day])[0]
    assert row.status == "ok" and row.url == report and row.source == "af"
    assert row.cutoff == ""  # AF states no data cutoff
    assert (tmp_path / "text" / "af" / "2026-08-03.txt").exists()


def test_clean_telegram_post_keeps_lines():
    html = "<div>⚡️  Подразделения <b>«Центр»</b><br/>освободили  пункт<br/><br/><br/>Х</div>"
    assert clean_telegram_post(html) == "⚡️ Подразделения «Центр»\nосвободили пункт\n\nХ"


def test_parse_channel_page_uses_moscow_date():
    page = tg_post(11, "2026-07-04T22:30:00+00:00", "поздно") + tg_post(
        10, "2026-07-04T12:00:00+00:00", "днём"
    )
    posts = parse_channel_page(page, 3)
    assert [p.id for p in posts] == [10, 11]
    assert posts[0].local.date() == date(2026, 7, 4)
    assert posts[1].local.date() == date(2026, 7, 5)  # 22:30 UTC is 01:30 in Moscow
    assert posts[1].text == "поздно"


def test_claim_posts_and_report_text():
    page = tg_post(1, "2026-07-04T10:00:00+00:00", "Вручили награды") + tg_post(
        2, "2026-07-04T11:00:00+00:00", "Подразделения освободили населенный пункт Х"
    )
    posts = claim_posts(parse_channel_page(page, 3), CFG["collect"]["rumod"]["claim_pattern"])
    assert [p.id for p in posts] == [2]
    text = rumod_report(posts, "https://t.me/mod_russia/{id}", date(2026, 7, 4))
    assert text.splitlines()[2] == "## https://t.me/mod_russia/2 · 14:00"
    offset = text.index("освободили")
    assert sources.post_url_at(text, offset) == "https://t.me/mod_russia/2"
    assert sources.post_url_at(text, 0) is None
    assert find_cutoff(text, "rumod", "x") is None


def test_collect_rumod_crawls_back_and_splits_days(tmp_path):
    newest = tg_post(5, "2026-07-06T09:00:00+00:00", "ПВО перехвачены 10 беспилотников") + tg_post(
        6, "2026-07-06T10:00:00+00:00", "Вручили награды"
    )
    older = tg_post(3, "2026-07-05T09:00:00+00:00", "освободили населенный пункт А") + tg_post(
        4, "2026-07-05T10:00:00+00:00", "сбиты 5 беспилотников"
    )
    oldest = tg_post(1, "2026-07-03T09:00:00+00:00", "освободили Б")
    routes = {
        f"{TG}/robots.txt": (404, ""),
        f"{TG}/s/mod_russia": (200, newest),
        f"{TG}/s/mod_russia?before=5": (200, older),
        f"{TG}/s/mod_russia?before=3": (200, oldest),
    }
    days = [date(2026, 7, 4), date(2026, 7, 5), date(2026, 7, 6)]
    rows = Collector(CFG, make_fetcher(routes), data_dir=tmp_path).collect("rumod", days)
    assert [r.status for r in rows] == ["missing (no claim post)", "ok", "ok"]
    assert rows[1].url == "https://t.me/mod_russia/3"
    text = (tmp_path / "text" / "rumod" / "2026-07-05.txt").read_text()
    assert "mod_russia/3" in text and "mod_russia/4" in text
    assert "награды" not in (tmp_path / "text" / "rumod" / "2026-07-06.txt").read_text()


def test_a2_units_follow_the_gsu_dates_and_split():
    units = sources.a2_units("af", {"gold": {"substitutions": {"af-2026-07-29": "2026-07-30"}}})
    assert len(units) == 15
    assert units[:3] == [("2026-07-21", "dev"), ("2026-07-30", "dev"), ("2026-08-06", "dev")]
    assert units[3] == ("2026-08-14", "test") and units[-1] == ("2026-11-10", "test")
    assert sources.split_report_id("rumod-2026-07-21") == ("rumod", "2026-07-21")
