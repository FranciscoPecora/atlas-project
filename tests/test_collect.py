from datetime import date

import httpx
import pytest

from src.collect import (
    Collector,
    Fetcher,
    PermissionNotGranted,
    daterange,
    gsu_candidates,
    isw_url,
    parse_sitemap,
    read_manifest,
    write_manifest,
)
from src.config import config_hash, load_config

CFG = load_config()
TIERS = CFG["collect"]["gsu"]["slug_keyword_tiers"]
BASE = "https://armyinform.com.ua"


def test_corpus_window_is_120_days():
    days = daterange(CFG["corpus"]["start"], CFG["corpus"]["end"])
    assert len(days) == 120
    analysis = daterange(CFG["corpus"]["start"], CFG["corpus"]["analysis_end"])
    assert len(analysis) == 90


def test_isw_url_uses_lowercase_month_and_unpadded_day():
    url = isw_url(date(2026, 7, 9), CFG["collect"]["isw"]["url_template"])
    assert url.endswith("/russian-offensive-campaign-assessment-july-9-2026/")


def test_parse_sitemap():
    xml = "<urlset><url><loc>https://a/1/</loc></url><url><loc> https://a/2/ </loc></url></urlset>"
    assert parse_sitemap(xml) == ["https://a/1/", "https://a/2/"]


def test_gsu_candidates_filter_by_day_and_rank_by_tier():
    locs = [
        f"{BASE}/2026/07/29/vorog-vtratyv-za-dobu-genshtab-zsu/",
        f"{BASE}/2026/07/29/istoriya-vodiya/",
        f"{BASE}/2026/07/29/na-fronti-zafiksovano-272-boyezitknen/",
        f"{BASE}/2026/07/28/na-fronti-zafiksovano-250-boyezitknen/",
        f"{BASE}/2026/07/29/vidbyto-15-atak/",
    ]
    assert gsu_candidates(locs, date(2026, 7, 29), TIERS) == [locs[2], locs[0], locs[4]]


def test_config_hash_ignores_key_order():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def make_fetcher(routes: dict[str, tuple[int, str]], clock: Clock | None = None) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes.get(str(request.url), (404, ""))
        return httpx.Response(status, text=body)

    clock = clock or Clock()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher("test-agent", 3, 5, client=client, sleep=clock.sleep, clock=clock.now)


def test_fetcher_waits_between_requests():
    clock = Clock()
    f = make_fetcher({f"{BASE}/robots.txt": (200, ""), f"{BASE}/a/": (200, "ok")}, clock)
    f.get_text(f"{BASE}/a/")
    f.get_text(f"{BASE}/a/")
    assert clock.slept == [3, 3]  # robots, a, a: two waits of the full delay


def test_fetcher_refuses_paths_disallowed_by_robots():
    f = make_fetcher({f"{BASE}/robots.txt": (200, "User-agent: *\nDisallow: /wp-json/\n")})
    with pytest.raises(PermissionError):
        f.get_text(f"{BASE}/wp-json/wp/v2/posts")


def article(paragraph: str) -> str:
    return f'<h1>T</h1><div class="single-content"><p>{paragraph}</p></div>'


def test_collect_gsu_picks_first_candidate_with_morning_cutoff(tmp_path):
    day = date(2026, 7, 29)
    evening = f"{BASE}/2026/07/29/najbilshe-atak-genshtab-zsu/"
    morning = f"{BASE}/2026/07/29/vidbyto-atak/"
    sitemap = f"<urlset><loc>{evening}</loc><loc>{morning}</loc></urlset>"
    routes = {
        f"{BASE}/robots.txt": (200, ""),
        f"{BASE}/sitemap-posttype-post.202607.xml": (200, sitemap),
        evening: (200, article("Оперативна інформація станом на 16:00 29 липня")),
        morning: (200, article("з оперативною інформацією станом на 8:00 29 липня")),
    }
    row = Collector(CFG, make_fetcher(routes), data_dir=tmp_path).collect_gsu(day)
    assert row.status == "ok"
    assert row.url == morning
    assert row.cutoff == "08:00 29 липня"
    assert (tmp_path / "text" / "gsu" / "2026-07-29.txt").exists()
    assert (tmp_path / "raw" / "gsu" / "2026-07-29.html").exists()


def test_collect_gsu_reports_missing_day(tmp_path):
    routes = {
        f"{BASE}/robots.txt": (200, ""),
        f"{BASE}/sitemap-posttype-post.202607.xml": (200, "<urlset></urlset>"),
    }
    row = Collector(CFG, make_fetcher(routes), data_dir=tmp_path).collect_gsu(date(2026, 7, 29))
    assert row.status.startswith("missing")


def test_isw_collection_refuses_without_permission(tmp_path):
    assert CFG["collect"]["isw"]["enabled"] is False
    with pytest.raises(PermissionNotGranted):
        Collector(CFG, make_fetcher({}), data_dir=tmp_path).collect_isw(date(2026, 7, 19))


def test_manifest_upserts_on_date_and_source(tmp_path):
    from src.collect import ManifestRow

    path = tmp_path / "manifest.csv"
    write_manifest([ManifestRow("2026-07-29", "gsu", "", "", "", "missing", "t1")], path)
    write_manifest([ManifestRow("2026-07-29", "gsu", "u", "h", "c", "ok", "t2")], path)
    rows = read_manifest(path)
    assert len(rows) == 1 and rows[0]["status"] == "ok"


def test_collect_keeps_days_that_are_already_saved(tmp_path):
    from src.collect import ManifestRow

    text = tmp_path / "text" / "gsu" / "2026-07-29.txt"
    text.parent.mkdir(parents=True)
    text.write_text("saved text", encoding="utf-8")
    kept = ManifestRow("2026-07-29", "gsu", "u", "h", "c", "ok", "t1")
    write_manifest([kept], tmp_path / "manifest.csv")
    rows = Collector(CFG, make_fetcher({}), data_dir=tmp_path).collect("gsu", [date(2026, 7, 29)])
    assert rows == [kept]  # no request was made: the fetcher has no routes
    assert text.read_text(encoding="utf-8") == "saved text"
