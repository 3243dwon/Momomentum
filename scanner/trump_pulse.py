"""Trump pulse — what he's posting and what he's signing.

Two free sources, no API keys required:
  1. Truth Social posts via trumpstruth.org RSS (a public archive that
     mirrors @realDonaldTrump). 100 items per fetch, recent-first.
  2. Presidential documents (executive orders, proclamations, memoranda)
     via the federalregister.gov JSON API, filtered to president=donald-trump.

Why this matters for a momentum scanner: Trump's posts and EOs move
markets. A Truth Social post mentioning a ticker is a real catalyst signal
— historically NVDA, TSLA, X, BA have all moved on his posts. EOs on
tariffs / sanctions / deregulation move whole sectors.

The fetcher extracts ticker mentions from post text by matching against the
scan universe so the dashboard can link them. EO bodies are summarized via
abstract only (LLM-side analysis is the macro pipeline's job, not ours).

Writes data/trump_pulse.json. Throttled via the same refresh interval as
the political fetcher so we don't hammer either source.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scanner import config

log = logging.getLogger(__name__)

PULSE_FILE = config.DATA_DIR / "trump_pulse.json"

_TRUTH_RSS_URL = "https://www.trumpstruth.org/feed"
_FEDREG_BASE = "https://www.federalregister.gov/api/v1/documents.json"
_TIMEOUT_SECONDS = 20
_TRUTH_POST_LIMIT = 50
_FEDREG_DAYS_LOOKBACK = 60  # roughly 2 months of EOs / proclamations
_USER_AGENT = "Momentum-Scanner makutanaka816@gmail.com"

# Common 2-4 letter words that look like tickers but aren't. Filtering these
# out cuts the false-positive rate on ticker extraction dramatically. Lower
# case in the set, comparison is case-insensitive vs. uppercase matches.
_TICKER_STOPWORDS = {
    "USA", "USD", "EU", "UK", "UN", "DC", "NY", "LA", "TX", "FL", "CA",
    "CEO", "CFO", "COO", "CIO", "IRS", "FBI", "CIA", "FAA", "FDA", "DOJ",
    "FBI", "ICE", "BLM", "NRA", "AFL", "CIO", "GDP", "CPI", "PCE",
    "WH", "OK", "AM", "PM", "ET", "PT", "CT", "MT", "EST", "PST",
    "ALL", "AND", "ARE", "BUT", "FOR", "HAS", "HER", "HIS", "NOT", "ONE",
    "OUR", "OUT", "SHE", "THE", "TWO", "WAS", "WHO", "WHY", "YOU", "ANY",
    "BIG", "BAD", "BAY", "DAY", "FAR", "FEW", "HIT", "JOB", "KEY", "LAW",
    "LOW", "MAN", "MAY", "NEW", "NOW", "OFF", "OLD", "OWN", "PAY", "RUN",
    "SAY", "SEE", "TOP", "WIN", "YES", "GO", "DO", "BE", "IS", "WE", "US",
    "IT", "TO", "AT", "OF", "ON", "IN", "NO", "SO", "UP", "OR", "BY", "AN",
    "IF", "ME", "MY", "AS",
}


def _fetch(url: str, headers: dict | None = None) -> httpx.Response | None:
    try:
        merged = {"User-Agent": _USER_AGENT}
        if headers:
            merged.update(headers)
        return httpx.get(url, headers=merged, timeout=_TIMEOUT_SECONDS, follow_redirects=True)
    except Exception as e:
        log.warning("Trump pulse fetch failed for %s: %s", url, e)
        return None


def _strip_html(s: str) -> str:
    """Truth Social posts come wrapped in <p>...</p> with HTML entities. Strip
    tags, decode entities, collapse whitespace — we want plain text."""
    if not s:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", s)
    decoded = html.unescape(no_tags)
    return re.sub(r"\s+", " ", decoded).strip()


def _parse_rss_items(xml_text: str) -> list[dict]:
    """Tiny RSS 2.0 parser — we only need title/pubDate/description/link.
    Avoids pulling in feedparser as a dep (it's already used by scanner.news
    but I'd rather keep this module self-contained for future portability)."""
    out: list[dict] = []
    for m in re.finditer(r"<item>(.*?)</item>", xml_text, re.DOTALL):
        block = m.group(1)

        def grab(field: str) -> str | None:
            mm = re.search(rf"<{field}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{field}>", block, re.DOTALL)
            return mm.group(1).strip() if mm else None

        out.append({
            "title": grab("title"),
            "pubDate": grab("pubDate"),
            "description": grab("description"),
            "link": grab("link"),
            "guid": grab("guid"),
        })
    return out


def _parse_rss_date(s: str | None) -> str | None:
    """RSS uses RFC 2822 dates ('Mon, 01 Jun 2026 05:03:51 +0000'). Convert
    to ISO-8601 for downstream consistency. Returns None if unparseable."""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except Exception:
        return None


# Trump signs nearly every post with his initials — "President DJT",
# "DONALD J. TRUMP", "President DONALD J. TRUMP". Those are signatures, NOT
# stock mentions, but "DJT" is also the Trump Media ticker, so naive bare-word
# extraction would tag the stock on every single post. Strip these before
# extracting, and require DJT in explicit cashtag form ($DJT) to ever count.
_SIGNATURE_RE = re.compile(
    r"\s*[-–—]?\s*(?:President\s+)?(?:DONALD\s+J\.?\s+TRUMP|DJT)\.?\s*$",
    re.IGNORECASE,
)
# Tickers whose symbol collides with Trump's initials / common signatures —
# only counted when cashtag-prefixed, never as a bare uppercase token.
_CASHTAG_ONLY = {"DJT"}


def _strip_signature(text: str) -> str:
    """Remove a trailing Trump signature so it doesn't read as a ticker. Runs
    a couple of times in case of stacked sign-offs."""
    prev = None
    out = text
    for _ in range(3):
        out = _SIGNATURE_RE.sub("", out).rstrip()
        if out == prev:
            break
        prev = out
    return out


def _extract_tickers(text: str, universe: set[str]) -> list[str]:
    """Pull plausible ticker mentions from one post. Two patterns:
      - $TSLA   (dollar-prefixed, 1-5 caps) — high-confidence
      - TSLA    (whitespace-bounded, 2-5 caps) — must be in universe AND not
                a known stopword to count

    DJT is special-cased: counted only as a $DJT cashtag, never bare, because
    his initials sign every post. Returns deduped uppercase tickers in order.
    """
    if not text:
        return []
    seen: list[str] = []

    def add(t: str) -> None:
        t = t.upper()
        if t and t not in seen:
            seen.append(t)

    # Dollar-prefixed: anything $XXX is intent-marked, accept even if not in
    # universe (rare tickers, watchlist additions, etc.)
    for m in re.finditer(r"\$([A-Z]{1,5})\b", text):
        add(m.group(1))

    # Bare uppercase: strip the signature first, then require universe
    # membership. Skip cashtag-only collisions (DJT) entirely here.
    body = _strip_signature(text)
    for m in re.finditer(r"\b([A-Z]{2,5})\b", body):
        t = m.group(1)
        if t in _TICKER_STOPWORDS or t in _CASHTAG_ONLY:
            continue
        if t in universe:
            add(t)
    return seen


def fetch_truth_social(universe: set[str]) -> list[dict]:
    """Pull recent posts from trumpstruth.org RSS, normalize, tag tickers."""
    resp = _fetch(_TRUTH_RSS_URL)
    if resp is None or resp.status_code != 200:
        log.warning("Truth Social fetch returned %s", resp.status_code if resp else "no-response")
        return []

    items = _parse_rss_items(resp.text)
    posts: list[dict] = []
    for it in items[:_TRUTH_POST_LIMIT]:
        text = _strip_html(it.get("description") or it.get("title") or "")
        # The "title" in this feed is usually identical to the body, sometimes
        # truncated. Prefer the description (full body) when both exist.
        posts.append({
            "ts": _parse_rss_date(it.get("pubDate")),
            "text": text,
            "url": it.get("link"),
            "ticker_mentions": _extract_tickers(text, universe),
        })
    return posts


def fetch_presidential_documents() -> list[dict]:
    """Pull Trump's signed Presidential Documents (EOs, proclamations, memos)
    from Federal Register in the last ~60 days. Returns the most recent first."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_FEDREG_DAYS_LOOKBACK)).date().isoformat()
    # Federal Register's API uses Rails-style `key[]=v` bracket notation. The
    # API returns the full document body by default, which has everything we
    # need (title / type / signing_date / abstract / html_url) — no need for
    # a fields[] filter (which the API actually rejects with 400).
    params = {
        "conditions[president]": "donald-trump",
        "conditions[type][]": "PRESDOCU",
        "conditions[publication_date][gte]": cutoff,
        "order": "newest",
        "per_page": "40",
    }
    resp = _fetch(_FEDREG_BASE + "?" + _build_query(params))
    if resp is None or resp.status_code != 200:
        log.warning("Federal Register fetch returned %s", resp.status_code if resp else "no-response")
        return []
    try:
        data = resp.json()
    except Exception as e:
        log.warning("Federal Register response parse failed: %s", e)
        return []
    out: list[dict] = []
    for r in data.get("results", []):
        out.append({
            "title": r.get("title"),
            "type": r.get("presidential_document_type") or r.get("type"),
            "signing_date": r.get("signing_date") or r.get("publication_date"),
            "publication_date": r.get("publication_date"),
            "document_number": r.get("document_number"),
            "html_url": r.get("html_url"),
            "abstract": r.get("abstract"),
        })
    return out


def _build_query(params: dict) -> str:
    """httpx auto-encodes lists but the Rails-style `key[]=v1&key[]=v2`
    expansion isn't its default. Do it ourselves to be explicit."""
    from urllib.parse import quote
    parts: list[str] = []
    for k, v in params.items():
        if isinstance(v, list):
            for item in v:
                parts.append(f"{quote(k)}={quote(str(item))}")
        else:
            parts.append(f"{quote(k)}={quote(str(v))}")
    return "&".join(parts)


def _load_universe() -> set[str]:
    """Best-effort load of scanned tickers so we can ground ticker extraction
    in real symbols. Empty set on any failure → only $-prefixed matches work."""
    universe_file = config.DATA_DIR / "universe.json"
    if not universe_file.exists():
        return set()
    try:
        data = json.loads(universe_file.read_text())
        tickers = data.get("tickers") if isinstance(data, dict) else data
        if isinstance(tickers, list):
            return {t.upper() for t in tickers if isinstance(t, str)}
    except Exception as e:
        log.warning("Trump pulse: universe load failed: %s", e)
    return set()


def _should_refresh(now: datetime) -> bool:
    if not PULSE_FILE.exists():
        return True
    try:
        data = json.loads(PULSE_FILE.read_text())
        gen = data.get("generated_at")
        if not gen:
            return True
        last = datetime.fromisoformat(gen)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds() >= config.POLITICAL_REFRESH_SECONDS
    except Exception:
        return True


def fetch_and_save(now: datetime | None = None) -> dict:
    """Fetch Truth Social + Federal Register, write data/trump_pulse.json."""
    now = now or datetime.now(timezone.utc)
    if not _should_refresh(now):
        log.info("Trump pulse: cache fresh, skipping fetch")
        try:
            return json.loads(PULSE_FILE.read_text())
        except Exception:
            pass

    universe = _load_universe()
    posts = fetch_truth_social(universe)
    docs = fetch_presidential_documents()

    payload = {
        "generated_at": now.isoformat(),
        "sources": {
            "truth_social": "trumpstruth.org RSS (mirrors @realDonaldTrump)",
            "presidential_documents": "federalregister.gov API (president=donald-trump)",
        },
        "truth_post_count": len(posts),
        "document_count": len(docs),
        "tickers_mentioned": sorted({t for p in posts for t in p["ticker_mentions"]}),
        "truth_posts": posts,
        "presidential_documents": docs,
    }
    PULSE_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Trump pulse: %d posts (%d unique ticker mentions), %d presidential documents",
        len(posts), len(payload["tickers_mentioned"]), len(docs),
    )
    return payload
