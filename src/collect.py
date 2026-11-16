"""Collect daily reports for the corpus window.

    uv run python -m src.collect --source gsu --dates 2026-07-21,2026-07-29,2026-08-06
    uv run python -m src.collect --source gsu            # whole corpus window

Raw HTML goes to data/raw/<source>/<date>.html and cleaned text to
data/text/<source>/<date>.txt (both git-ignored). data/manifest.csv records
date, source, url, sha256 of the cleaned text, stated cutoff and status.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
import urllib.robotparser
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from src.clean import clean_gsu, clean_isw, find_cutoff, sha256_text
from src.config import load_config

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.csv"
MANIFEST_FIELDS = ["date", "source", "url", "sha256", "cutoff", "status", "fetched_at"]
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


class PermissionNotGranted(RuntimeError):
    pass


class Fetcher:
    """HTTP client that obeys robots.txt and waits `delay` seconds between requests."""

    def __init__(
        self,
        user_agent: str,
        delay: float,
        timeout: float,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_agent = user_agent
        self.delay = delay
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True
        )
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _wait(self) -> None:
        if self._last is not None:
            remaining = self.delay - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()

    def _get(self, url: str) -> httpx.Response:
        self._wait()
        return self.client.get(url)

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            resp = self._get(host + "/robots.txt")
            rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            self._robots[host] = rp
        return self._robots[host].can_fetch(self.user_agent, url)

    def get_text(self, url: str) -> str:
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        resp = self._get(url)
        resp.raise_for_status()
        return resp.text


@dataclass
class ManifestRow:
    date: str
    source: str
    url: str
    sha256: str
    cutoff: str
    status: str
    fetched_at: str


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def isw_url(day: date, template: str) -> str:
    return template.format(month=day.strftime("%B").lower(), day=day.day, year=day.year)


def parse_sitemap(xml: str) -> list[str]:
    return LOC.findall(xml)


def gsu_candidates(locs: Iterable[str], day: date, tiers: list[list[str]]) -> list[str]:
    """Posts published on `day`, ordered by the first keyword tier their slug matches.

    Posts matching no tier are dropped. Order inside a tier follows the sitemap.
    """
    marker = day.strftime("/%Y/%m/%d/")
    ranked: list[tuple[int, int, str]] = []
    for pos, url in enumerate(locs):
        if marker not in url:
            continue
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        for rank, keywords in enumerate(tiers):
            if any(k in slug for k in keywords):
                ranked.append((rank, pos, url))
                break
    return [u for _, _, u in sorted(ranked)]


def is_gsu_morning(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


class Collector:
    def __init__(self, cfg: dict, fetcher: Fetcher, data_dir: Path = DATA) -> None:
        self.cfg = cfg
        self.fetcher = fetcher
        self.data_dir = data_dir
        self._sitemaps: dict[str, list[str]] = {}

    def _save(self, source: str, day: date, html: str, text: str) -> None:
        for sub, ext, body in (("raw", "html", html), ("text", "txt", text)):
            path = self.data_dir / sub / source / f"{day.isoformat()}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")

    def _row(self, day: date, source: str, url: str, text: str, status: str) -> ManifestRow:
        gsu_pattern = self.cfg["collect"]["gsu"]["cutoff_pattern"]
        return ManifestRow(
            date=day.isoformat(),
            source=source,
            url=url,
            sha256=sha256_text(text) if text else "",
            cutoff=(find_cutoff(text, source, gsu_pattern) or "") if text else "",
            status=status,
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def collect_isw(self, day: date) -> ManifestRow:
        icfg = self.cfg["collect"]["isw"]
        if not icfg["enabled"]:
            raise PermissionNotGranted(
                "ISW collection is disabled until written permission arrives. "
                "See docs/permissions.md; then set collect.isw.enabled in config.yaml."
            )
        url = isw_url(day, icfg["url_template"])
        try:
            html = self.fetcher.get_text(url)
        except httpx.HTTPError as e:
            return self._row(day, "isw", url, "", f"error: {e.__class__.__name__}")
        text = clean_isw(html)
        self._save("isw", day, html, text)
        return self._row(day, "isw", url, text, "ok")

    def _month_locs(self, day: date) -> list[str]:
        key = day.strftime("%Y%m")
        if key not in self._sitemaps:
            url = self.cfg["collect"]["gsu"]["sitemap_template"].format(yyyymm=key)
            self._sitemaps[key] = parse_sitemap(self.fetcher.get_text(url))
        return self._sitemaps[key]

    def collect_gsu(self, day: date) -> ManifestRow:
        gcfg = self.cfg["collect"]["gsu"]
        candidates = gsu_candidates(self._month_locs(day), day, gcfg["slug_keyword_tiers"])
        errors = 0
        for url in candidates:
            try:
                html = self.fetcher.get_text(url)
            except httpx.HTTPError:
                errors += 1
                continue
            text = clean_gsu(html)
            if is_gsu_morning(text, gcfg["cutoff_pattern"]):
                self._save("gsu", day, html, text)
                return self._row(day, "gsu", url, text, "ok")
        status = f"missing ({len(candidates)} candidates, {errors} http errors)"
        return self._row(day, "gsu", "", "", status)

    def collect(self, source: str, days: Iterable[date]) -> list[ManifestRow]:
        fn = self.collect_isw if source == "isw" else self.collect_gsu
        rows = []
        for day in days:
            row = fn(day)
            print(f"{row.date} {row.source} {row.status} {row.url}")
            rows.append(row)
        return rows


def read_manifest(path: Path = MANIFEST) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_manifest(rows: list[ManifestRow], path: Path = MANIFEST) -> None:
    """Upsert rows keyed on (date, source) and write the manifest sorted."""
    merged = {(r["date"], r["source"]): r for r in read_manifest(path)}
    for r in rows:
        merged[(r.date, r.source)] = asdict(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        for key in sorted(merged):
            w.writerow(merged[key])


def reindex(cfg: dict, path: Path = MANIFEST, data_dir: Path = DATA) -> list[dict[str, str]]:
    """Recompute sha256 and cutoff of every collected report from its saved text."""
    pattern = cfg["collect"]["gsu"]["cutoff_pattern"]
    rows = read_manifest(path)
    for r in rows:
        if r["status"] != "ok":
            continue
        text = (data_dir / "text" / r["source"] / f"{r['date']}.txt").read_text(encoding="utf-8")
        r["sha256"] = sha256_text(text)
        r["cutoff"] = find_cutoff(text, r["source"], pattern) or ""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["isw", "gsu"])
    ap.add_argument("--dates", help="comma-separated ISO dates; default is the corpus window")
    ap.add_argument("--reindex", action="store_true", help="recompute hashes from saved text")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.reindex:
        for r in reindex(cfg):
            print(r["date"], r["source"], r["status"], r["sha256"][:12], r["cutoff"])
        return
    if args.source is None:
        ap.error("--source is required unless --reindex")
    if args.dates:
        days = [date.fromisoformat(d) for d in args.dates.split(",")]
    else:
        days = daterange(cfg["corpus"]["start"], cfg["corpus"]["end"])
    c = cfg["collect"]
    fetcher = Fetcher(c["user_agent"], c["delay_seconds"], c["timeout_seconds"])
    rows = Collector(cfg, fetcher).collect(args.source, days)
    write_manifest(rows)
    ok = sum(r.status == "ok" for r in rows)
    print(f"{ok}/{len(rows)} collected; manifest: {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
