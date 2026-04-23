"""News ingestion: Alpaca per-ticker news + RSS macro feeds.

Per-ticker news used to come from Finviz scraping, but GitHub Actions runner
IPs get rate-limited / CAPTCHA-blocked during US business hours, so scans
were returning 0 ticker news most of the time. Alpaca's /v1beta1/news
endpoint takes the same API key as the bar fetcher, hits Benzinga's feed,
and works from any IP. One batch call covers all routed tickers.

A `seen` cache (data/cache/news_seen.json) prevents re-emitting the same URL
across scans; only items not in the cache and within the freshness window
make it to the LLM tiers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser

from scanner import config

log = logging.getLogger(__name__)

SEEN_FILE = config.CACHE_DIR / "news_seen.json"

FRESH_WINDOW = timedelta(hours=6)
SEEN_RETENTION = timedelta(hours=48)
NEWS_FETCH_WINDOW = timedelta(hours=12)  # Alpaca query window; fresh-filter narrows further
NEWS_BATCH_SIZE = 50  # Alpaca caps symbols per request; be conservative
NEWS_PER_REQUEST_LIMIT = 50  # items per page

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY")
ALPACA_API_SECRET = os.environ.get("ALPACA_API_SECRET")

try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest

    if ALPACA_API_KEY and ALPACA_API_SECRET:
        _NEWS_CLIENT: NewsClient | None = NewsClient(ALPACA_API_KEY, ALPACA_API_SECRET)
    else:
        _NEWS_CLIENT = None
except ImportError as _e:
    _NEWS_CLIENT = None
    log.warning("alpaca-py news import failed (%s); ticker news disabled", _e)

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


def fetch_ticker_news(tickers: Iterable[str]) -> dict[str, list[dict]]:
    """Fetch ticker news from Alpaca (Benzinga feed). One batch call fans out to
    all routed tickers. Returns {ticker: [item, ...]} matching the existing item
    schema; an article tagged to multiple symbols appears in each of their lists."""
    tickers = [t for t in tickers if t]
    out: dict[str, list[dict]] = {}
    if not tickers:
        return out
    if _NEWS_CLIENT is None:
        log.warning("Alpaca news client not initialized (missing keys?) — skipping ticker news")
        return out

    routed_set = set(tickers)
    start = _now() - NEWS_FETCH_WINDOW

    for i in range(0, len(tickers), NEWS_BATCH_SIZE):
        batch = tickers[i : i + NEWS_BATCH_SIZE]
        page_token: str | None = None
        pages = 0
        batch_items = 0
        while True:
            try:
                req = NewsRequest(
                    symbols=",".join(batch),
                    start=start,
                    limit=NEWS_PER_REQUEST_LIMIT,
                    sort="desc",
                    exclude_contentless=True,
                    page_token=page_token,
                )
                resp = _NEWS_CLIENT.get_news(req)
            except Exception as e:
                log.warning("Alpaca news batch fetch failed (%d symbols): %s: %s",
                            len(batch), type(e).__name__, e)
                break

            articles = _flatten_news_response(resp)
            if not articles:
                break

            for art in articles:
                url = getattr(art, "url", None) or f"alpaca-news-{getattr(art, 'id', '')}"
                headline = getattr(art, "headline", "") or ""
                publisher = getattr(art, "source", "") or "alpaca"
                created = getattr(art, "created_at", None)
                if not headline or not created:
                    continue
                published_iso = (
                    created.astimezone(timezone.utc).isoformat()
                    if hasattr(created, "astimezone")
                    else str(created)
                )
                item_id = _sha(f"alpaca:{getattr(art, 'id', url)}")
                symbols = getattr(art, "symbols", []) or []
                for sym in symbols:
                    if sym not in routed_set:
                        continue  # article tagged to a non-routed ticker — skip
                    out.setdefault(sym, []).append(
                        {
                            "id": item_id,
                            "source": "alpaca",
                            "publisher": publisher,
                            "ticker": sym,
                            "scope": "ticker",
                            "title": headline,
                            "url": url,
                            "published_at": published_iso,
                        }
                    )
                    batch_items += 1

            page_token = getattr(resp, "next_page_token", None) if hasattr(resp, "next_page_token") else None
            pages += 1
            if not page_token or pages >= 5:  # safety cap on pagination
                break

        log.debug("Alpaca news batch %d-%d: %d items distributed across %d tickers",
                  i, i + len(batch), batch_items, len({k for k, v in out.items() if v}))

    log.info("Alpaca news: %d tickers with news, %d total items",
             len(out), sum(len(v) for v in out.values()))
    return out


def _flatten_news_response(resp) -> list:
    """Alpaca SDK returns NewsSet with .data = {key: [News, ...]}. The key is
    sometimes the symbol, sometimes a single 'news' bucket — handle both, and
    also the fallback where resp is already a flat list."""
    data = getattr(resp, "data", None)
    if data is None:
        if isinstance(resp, list):
            return resp
        return []
    if isinstance(data, dict):
        flat: list = []
        for v in data.values():
            if isinstance(v, list):
                flat.extend(v)
        return flat
    if isinstance(data, list):
        return data
    return []


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
