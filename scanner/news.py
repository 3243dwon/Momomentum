"""News ingestion: Finviz per-ticker (only for routed tickers) + RSS macro feeds.

Per-ticker fetch is rate-limited and only run for the small set of tickers
that pass the Tier 0 router — scraping Finviz for all 2,500 every 30min would
get the IP blocked and isn't useful (most tickers have no news).

A `seen` cache (data/cache/news_seen.json) prevents re-emitting the same URL
across scans; only items not in the cache and within the freshness window
make it to the LLM tiers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup

from scanner import config

log = logging.getLogger(__name__)

SEEN_FILE = config.CACHE_DIR / "news_seen.json"

FRESH_WINDOW = timedelta(hours=6)
SEEN_RETENTION = timedelta(hours=48)
FINVIZ_REQUEST_DELAY_S = 1.0
FINVIZ_TIMEOUT_S = 15

FINVIZ_URL = "https://finviz.com/quote.ashx?t={ticker}&p=d"

MACRO_FEEDS = [
    ("federal_reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("cnbc_top", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("cnbc_markets", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("marketwatch_top", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("yahoo_finance", "https://finance.yahoo.com/news/rssindex"),
]

MACRO_KEYWORDS = re.compile(
    r"\b(fed|federal reserve|fomc|cpi|inflation|gdp|tariff|geopolit|opec|"
    r"china|russia|war|sanction|earnings season|jobs report|nonfarm|unemployment|"
    r"jpow|powell|rate cut|rate hike|hawkish|dovish|treasury|yield|recession)\b",
    re.IGNORECASE,
)


def _sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_seen() -> dict[str, str]:
    if not SEEN_FILE.exists():
        return {}
    try:
        seen = json.loads(SEEN_FILE.read_text())
        cutoff = _now() - SEEN_RETENTION
        return {k: v for k, v in seen.items() if datetime.fromisoformat(v) > cutoff}
    except Exception:
        return {}


def _save_seen(seen: dict[str, str]) -> None:
    SEEN_FILE.write_text(json.dumps(seen, indent=2))


def _parse_finviz_datetime(label: str, last_date: str | None) -> tuple[datetime | None, str]:
    """Finviz news rows are either 'Apr-18-26 09:30AM' or just '09:30AM' (same day).

    Returns (parsed datetime UTC, new last_date) — the last_date is propagated so
    same-day rows can resolve their date.
    """
    label = label.strip()
    parts = label.split(" ")
    if len(parts) == 2:
        date_part, time_part = parts
        last_date = date_part
    else:
        time_part = label
        date_part = last_date
    if not date_part:
        return None, last_date
    try:
        dt_naive = datetime.strptime(f"{date_part} {time_part}", "%b-%d-%y %I:%M%p")
    except ValueError:
        return None, last_date
    et = dt_naive.replace(tzinfo=config.MARKET_TZ)
    return et.astimezone(timezone.utc), last_date


def fetch_ticker_news(tickers: Iterable[str]) -> dict[str, list[dict]]:
    """Scrape Finviz news pages for each ticker. Polite 1 req/sec."""
    out: dict[str, list[dict]] = {}
    headers = {"User-Agent": config.USER_AGENT}
    for t in tickers:
        try:
            resp = requests.get(
                FINVIZ_URL.format(ticker=t), headers=headers, timeout=FINVIZ_TIMEOUT_S
            )
            if resp.status_code != 200:
                log.debug("Finviz %s: HTTP %s", t, resp.status_code)
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", id="news-table")
            if not table:
                continue
            items: list[dict] = []
            last_date: str | None = None
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                published, last_date = _parse_finviz_datetime(cells[0].get_text(), last_date)
                link = cells[1].find("a", class_="tab-link-news")
                if not link or not published:
                    continue
                source_span = cells[1].find("span")
                items.append(
                    {
                        "id": _sha(link["href"]),
                        "source": "finviz",
                        "publisher": (source_span.get_text(strip=True) if source_span else ""),
                        "ticker": t,
                        "scope": "ticker",
                        "title": link.get_text(strip=True),
                        "url": link["href"],
                        "published_at": published.isoformat(),
                    }
                )
            if items:
                out[t] = items
        except Exception as e:
            log.debug("Finviz fetch failed for %s: %s", t, e)
        time.sleep(FINVIZ_REQUEST_DELAY_S)
    return out


def fetch_macro_news() -> list[dict]:
    items: list[dict] = []
    for source_name, url in MACRO_FEEDS:
        try:
            parsed = feedparser.parse(url, agent=config.USER_AGENT)
        except Exception as e:
            log.debug("RSS %s failed: %s", source_name, e)
            continue
        for entry in parsed.entries[:50]:
            published = _entry_published(entry)
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            if not title or not link:
                continue
            items.append(
                {
                    "id": _sha(link),
                    "source": source_name,
                    "publisher": source_name,
                    "ticker": None,
                    "scope": "macro",
                    "title": title,
                    "url": link,
                    "published_at": (published or _now()).isoformat(),
                }
            )
    return items


def _entry_published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def filter_fresh(items: list[dict], seen: dict[str, str]) -> list[dict]:
    """Drop items already in `seen` cache or older than the freshness window."""
    cutoff = _now() - FRESH_WINDOW
    fresh: list[dict] = []
    for item in items:
        if item["id"] in seen:
            continue
        try:
            pub = datetime.fromisoformat(item["published_at"])
        except Exception:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub < cutoff:
            continue
        fresh.append(item)
    return fresh


def mark_seen(items: list[dict], seen: dict[str, str]) -> dict[str, str]:
    now_iso = _now().isoformat()
    for item in items:
        seen.setdefault(item["id"], now_iso)
    return seen


def is_macro_relevant(item: dict) -> bool:
    """Quick keyword pre-filter for macro items before they hit Haiku."""
    return bool(MACRO_KEYWORDS.search(item.get("title", "")))


def ingest(routed_tickers: list[str]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Top-level: fetch + filter. Returns (ticker_news, macro_news)."""
    seen = _load_seen()

    log.info("Fetching news for %d routed tickers", len(routed_tickers))
    raw_ticker = fetch_ticker_news(routed_tickers)
    fresh_ticker = {
        t: filter_fresh(items, seen) for t, items in raw_ticker.items()
    }
    fresh_ticker = {t: items for t, items in fresh_ticker.items() if items}

    log.info("Fetching macro RSS feeds")
    raw_macro = fetch_macro_news()
    fresh_macro = filter_fresh(raw_macro, seen)
    # Macro relevance is decided by Haiku in Tier 1, not a keyword pre-filter
    # (the regex was rejecting clearly-relevant stories with non-canonical wording).

    all_fresh = [item for items in fresh_ticker.values() for item in items] + fresh_macro
    seen = mark_seen(all_fresh, seen)
    _save_seen(seen)

    log.info(
        "News ingest: %d fresh ticker items across %d tickers, %d fresh macro items",
        sum(len(v) for v in fresh_ticker.values()),
        len(fresh_ticker),
        len(fresh_macro),
    )
    return fresh_ticker, fresh_macro
