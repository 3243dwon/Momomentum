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
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from scanner import config

log = logging.getLogger(__name__)

PULSE_FILE = config.DATA_DIR / "trump_pulse.json"

# Primary source: a full archive (33k+ posts back to 2022) refreshed every few
# minutes. Gives real history so we can answer "when did Trump last name X" and
# catch by-name mentions across a meaningful window — the 100-post RSS can't.
_TRUTH_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
# Fallback if the archive is unreachable — recent ~100 posts only.
_TRUTH_RSS_URL = "https://www.trumpstruth.org/feed"
_FEDREG_BASE = "https://www.federalregister.gov/api/v1/documents.json"
_TIMEOUT_SECONDS = 45  # archive is ~18MB
_TRUTH_LOOKBACK_DAYS = 90   # window we scan for ticker mentions
_TRUTH_DISPLAY_LIMIT = 40   # most-recent posts kept for the feed view
_FEDREG_DAYS_LOOKBACK = 60  # roughly 2 months of EOs / proclamations
_USER_AGENT = "Momentum-Scanner makutanaka816@gmail.com"
_COMPANY_ALIASES_FILE = config.DATA_DIR / "company_aliases.json"

# Trump's market-moving COMMENTS increasingly arrive as press remarks reported
# by news wires (Reuters / CNBC / Bloomberg) — "Trump says Apple to work with
# Intel", "U.S. to take 10% Intel stake" — NOT as Truth Social posts or signed
# EOs. Truth Social + Federal Register miss every one of those. We close the gap
# with a Google News RSS query for Trump business news, then keep only the
# headlines that name a universe ticker (same high-precision extraction as
# posts). Free, no key required.
_TRUMP_NEWS_RSS = "https://news.google.com/rss/search"
_TRUMP_NEWS_QUERY = (
    "Trump (stock OR shares OR tariff OR tariffs OR chips OR semiconductor OR "
    "stake OR acquisition OR merger OR deal OR company OR factory OR plant OR "
    "investment OR trade OR sanctions OR antitrust) when:3d"
)
_TRUMP_NEWS_LIMIT = 60

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
    # Trump-ism / political acronyms that show up in parentheticals and collide
    # with real tickers: "(TDS)" = Trump Derangement Syndrome (not the telecom
    # TDS), "(MAGA)", "(RINO)", etc.
    "TDS", "MAGA", "RINO", "NATO", "FISA", "RICO", "POTUS", "FLOTUS",
    "SCOTUS", "GOP", "DNC", "RNC", "DHS", "DOD", "DOE", "NSA", "MSNBC",
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


def _load_aliases() -> dict[str, list[str]]:
    """Load the company-name → ticker alias map. Returns {ticker: [names...]}
    with names lowercased for case-insensitive matching. Empty on failure."""
    if not _COMPANY_ALIASES_FILE.exists():
        return {}
    try:
        data = json.loads(_COMPANY_ALIASES_FILE.read_text())
        aliases = data.get("aliases", {})
        return {
            t.upper(): [n.lower() for n in names]
            for t, names in aliases.items()
            if isinstance(names, list)
        }
    except Exception as e:
        log.warning("Trump pulse: alias load failed: %s", e)
        return {}


# Some company names double as common words in other contexts. Count them only
# when a disambiguating word ISN'T sitting next to the match. The big one:
# "intel" = Intel the chipmaker, but also "intelligence" (ex-intel official,
# intel agency / community / report). Window-checked, so "Intel Stock" still
# counts while "ex-intel official" does not.
_ALIAS_CONTEXT_GUARDS: dict[str, list[str]] = {
    "intel": [
        "intelligence", "official", "agency", "agencies", "community",
        "officer", "operation", "cia", "fbi", "dni", "nsa", "classified",
        "sources", "deception", "spy", "surveillance", "informant",
        "gathering", "report", "briefing", "leak",
    ],
    "amazon": ["rainforest", "jungle", "river", "brazil", "forest"],
    "oracle": ["omaha", "buffett", "warren", "delphi"],
}
_GUARD_WINDOW = 30  # chars each side of a match to scan for a guard word


def _extract_tickers(text: str, universe: set[str], aliases: dict[str, list[str]] | None = None) -> list[str]:
    """Pull plausible ticker mentions from one post. Three patterns:
      - $TSLA            cashtag, 1-5 caps — high-confidence, accepted as-is
      - TSLA             bare uppercase, 2-5 caps — must be in universe
      - "Tesla"/"Intel"  company NAME via the alias map — case-insensitive

    The name pass is the important one: Trump writes 'Intel', 'Apple',
    'Nvidia' — not 'INTC'/'AAPL'/'NVDA'. Without aliases we'd miss every
    by-name mention, which is how he actually talks about stocks.

    DJT is special-cased: counted only as a $DJT cashtag, never bare/by-name,
    because his initials sign every post. Returns deduped tickers in order.
    """
    if not text:
        return []
    seen: list[str] = []

    def add(t: str) -> None:
        t = t.upper()
        if t and t not in seen:
            seen.append(t)

    # Strip the trailing signature once — used by all passes.
    body = _strip_signature(text)

    # 1) Dollar-prefixed cashtags — intent-marked, accept even if not in universe.
    for m in re.finditer(r"\$([A-Z]{1,5})\b", text):
        add(m.group(1))

    # 2) Ticker-in-parentheses, e.g. "Palantir Technologies (PLTR)". A strong
    #    intent signal. Require universe membership + not a stopword so we don't
    #    catch "(CNN)" / "(USA)" / "(R-FL)" style parentheticals.
    for m in re.finditer(r"\(([A-Z]{2,5})\)", body):
        t = m.group(1)
        if t in _TICKER_STOPWORDS or t in _CASHTAG_ONLY:
            continue
        if t in universe:
            add(t)

    # 3) Company NAMES via the alias map — case-insensitive, word-boundary.
    #    This is the high-value pass: Trump writes "Intel"/"Palantir"/"Nvidia",
    #    not the ticker symbol. Guarded aliases (e.g. "intel") are skipped when
    #    a disambiguating word sits next to the match, so "ex-intel official"
    #    doesn't tag INTC.
    if aliases:
        low = body.lower()
        for ticker, names in aliases.items():
            hit = False
            for name in names:
                guards = _ALIAS_CONTEXT_GUARDS.get(name)
                for m in re.finditer(r"\b" + re.escape(name) + r"\b", low):
                    if guards:
                        window = low[max(0, m.start() - _GUARD_WINDOW): m.end() + _GUARD_WINDOW]
                        if any(g in window for g in guards):
                            continue  # disambiguating context — not the company
                    hit = True
                    break
                if hit:
                    break
            if hit:
                add(ticker)

    # NOTE: deliberately NO bare-uppercase pass. Trump writes in ALL CAPS
    # constantly ("TEN POINT PLAN", "LIVE", "FUND ICE", "AI"), which collides
    # with tickers (TEN, LIVE, FUND, AI) in a 5k-name universe and floods the
    # output with false positives. Cashtags + parens + names are high-precision.
    return seen


def _fetch_archive_posts(now: datetime) -> list[dict] | None:
    """Pull the deep CNN archive, filter to the lookback window, normalize to
    {ts, text, url}. Returns None on failure so the caller can fall back to RSS."""
    resp = _fetch(_TRUTH_ARCHIVE_URL)
    if resp is None or resp.status_code != 200:
        log.warning("Truth archive fetch returned %s", resp.status_code if resp else "no-response")
        return None
    try:
        data = resp.json()
    except Exception as e:
        log.warning("Truth archive parse failed: %s", e)
        return None
    raw = data if isinstance(data, list) else data.get("posts") or data.get("data") or []
    if not raw:
        return None

    cutoff = (now - timedelta(days=_TRUTH_LOOKBACK_DAYS)).isoformat()
    out: list[dict] = []
    for p in raw:
        ts = p.get("created_at") or p.get("date") or ""
        if ts and ts < cutoff:
            continue
        text = _strip_html(p.get("content") or "")
        if not text:
            continue
        out.append({"ts": ts or None, "text": text, "url": p.get("url")})
    # Most-recent first.
    out.sort(key=lambda x: x["ts"] or "", reverse=True)
    return out


def _fetch_rss_posts() -> list[dict]:
    """Fallback: recent ~100 posts from trumpstruth.org RSS as {ts, text, url}."""
    resp = _fetch(_TRUTH_RSS_URL)
    if resp is None or resp.status_code != 200:
        log.warning("Truth Social RSS returned %s", resp.status_code if resp else "no-response")
        return []
    out: list[dict] = []
    for it in _parse_rss_items(resp.text):
        text = _strip_html(it.get("description") or it.get("title") or "")
        out.append({"ts": _parse_rss_date(it.get("pubDate")), "text": text, "url": it.get("link")})
    return out


def fetch_truth_social(universe: set[str], aliases: dict[str, list[str]], now: datetime) -> tuple[list[dict], str]:
    """Get Trump's recent posts (archive preferred, RSS fallback), tag each
    with ticker mentions. Returns (posts, source_label)."""
    raw = _fetch_archive_posts(now)
    source = "ix.cnn.io archive (33k posts, 90d window)"
    if not raw:
        raw = _fetch_rss_posts()
        source = "trumpstruth.org RSS (fallback, recent only)"

    posts: list[dict] = []
    for p in raw:
        posts.append({
            "ts": p["ts"],
            "text": p["text"],
            "url": p["url"],
            "ticker_mentions": _extract_tickers(p["text"], universe, aliases),
        })
    return posts, source


def fetch_trump_news(universe: set[str], aliases: dict[str, list[str]], now: datetime) -> list[dict]:
    """Trump's market-moving COMMENTS as reported by news wires — the catalyst
    class Truth Social + Federal Register can't see. Google News RSS, then keep
    only headlines that name a universe ticker (same extraction as posts), so the
    noise of general Trump political news is filtered to market-relevant comments.
    Returns {ts, text, url, ticker_mentions, source} dicts, newest-ish first."""
    from urllib.parse import quote

    url = f"{_TRUMP_NEWS_RSS}?q={quote(_TRUMP_NEWS_QUERY)}&hl=en-US&gl=US&ceid=US:en"
    resp = _fetch(url)
    if resp is None or resp.status_code != 200:
        log.warning("Trump news RSS returned %s", resp.status_code if resp else "no-response")
        return []

    out: list[dict] = []
    seen_urls: set[str] = set()
    for it in _parse_rss_items(resp.text):
        title = _strip_html(it.get("title") or "")
        if not title:
            continue
        # Google News appends " - Publisher"; drop it before extraction + display
        # so the publisher name can't be mistaken for a company and the feed reads
        # clean.
        headline = re.sub(r"\s+[-–—]\s+[^-–—]+$", "", title).strip() or title
        tickers = _extract_tickers(headline, universe, aliases)
        if not tickers:
            continue
        link = it.get("link")
        if link and link in seen_urls:
            continue
        if link:
            seen_urls.add(link)
        out.append({
            "ts": _parse_rss_date(it.get("pubDate")),
            "text": headline,
            "url": link,
            "ticker_mentions": tickers,
            "source": "news",
        })
        if len(out) >= _TRUMP_NEWS_LIMIT:
            break
    out.sort(key=lambda x: x["ts"] or "", reverse=True)
    return out


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
    aliases = _load_aliases()
    posts, truth_source = fetch_truth_social(universe, aliases, now)
    for p in posts:
        p.setdefault("source", "truth_social")
    # Third source: Trump comments reported by news wires that name a ticker.
    news_posts = fetch_trump_news(universe, aliases, now)
    docs = fetch_presidential_documents()

    # Build a per-ticker mention summary over the whole window: how many times
    # Trump named it, when he last did, and a short excerpt of that post. This
    # is what powers "Trump mentioned INTC 5x · last 3d ago" in the UI.
    mention_summary: dict[str, dict] = {}
    mention_posts: list[dict] = []
    for p in posts:
        if not p["ticker_mentions"]:
            continue
        mention_posts.append(p)
        for t in p["ticker_mentions"]:
            s = mention_summary.setdefault(t, {"count": 0, "last_ts": None, "last_excerpt": None, "last_url": None})
            s["count"] += 1
            # posts are newest-first, so the first time we see a ticker is its
            # most recent mention.
            if s["last_ts"] is None:
                s["last_ts"] = p["ts"]
                s["last_excerpt"] = p["text"][:240]
                s["last_url"] = p["url"]

    # Keep the JSON lean: the recent N posts for the feed view, plus every post
    # in the window that named a ticker (the high-signal ones), deduped.
    display_posts = posts[:_TRUTH_DISPLAY_LIMIT]
    seen_urls = {p.get("url") for p in display_posts}
    kept = display_posts + [p for p in mention_posts if p.get("url") not in seen_urls]

    # Fold the news-reported comments' tickers into the mentioned set so the
    # dashboard badges (which key off tickers_mentioned) light up for them too.
    news_tickers = {t for p in news_posts for t in p["ticker_mentions"]}
    all_tickers = sorted(set(mention_summary.keys()) | news_tickers)

    payload = {
        "generated_at": now.isoformat(),
        "sources": {
            "truth_social": truth_source,
            "news_comments": "Google News RSS (Trump market-comment headlines naming a ticker)",
            "presidential_documents": "federalregister.gov API (president=donald-trump)",
        },
        "window_days": _TRUTH_LOOKBACK_DAYS,
        "truth_post_count": len(posts),
        "news_post_count": len(news_posts),
        "document_count": len(docs),
        "tickers_mentioned": all_tickers,
        "mention_summary": mention_summary,
        "truth_posts": kept,
        "news_posts": news_posts,
        "presidential_documents": docs,
    }
    PULSE_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Trump pulse: %d posts in %dd window via %s (%d named) + %d news comments "
        "(%d named), %d docs",
        len(posts), _TRUTH_LOOKBACK_DAYS, truth_source.split()[0],
        len(mention_summary), len(news_posts), len(news_tickers), len(docs),
    )
    return payload


# --- Feishu notification for fresh Trump stock mentions ----------------------
# When Trump names a stock on Truth Social, that's a catalyst worth a ping.
# We notify only on NEW posts (deduped by URL) within a recency window, so the
# channel never gets the 90-day backlog or a repeat of the same post.

_TRUMP_NOTIFIED_FILE = config.CACHE_DIR / "trump_notified.json"
_NOTIFY_RECENCY_HOURS = 48      # only ping mentions this fresh
_NOTIFY_MAX_POSTS = 3           # cap posts per card so it can't balloon
_SITE_URL = os.environ.get("SITE_URL", "https://momomentum.vercel.app")


def _load_notified() -> list[str]:
    try:
        d = json.loads(_TRUMP_NOTIFIED_FILE.read_text())
        urls = d.get("notified_urls", [])
        return urls if isinstance(urls, list) else []
    except Exception:
        return []


def _save_notified(urls: list[str]) -> None:
    # Keep the most recent ~300 so the file can't grow unbounded.
    try:
        _TRUMP_NOTIFIED_FILE.write_text(json.dumps({"notified_urls": urls[-300:]}, indent=2))
    except Exception as e:
        log.warning("Trump notify: could not persist state: %s", e)


def _rel_time(ts: str | None, now: datetime) -> str:
    """Compact 'Xh ago' / 'Xd ago' for a post timestamp."""
    if not ts:
        return ""
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except Exception:
        return ""
    secs = (now - t).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def _build_mention_alert(posts: list[dict], rows_by_ticker: dict[str, dict],
                         now: datetime) -> dict:
    """Render fresh mention posts into a Feishu alert dict — one line per post."""
    from scanner.alerts.rules import _clip

    # Title lists the named tickers (deduped, in first-seen order).
    tickers: list[str] = []
    for p in posts:
        for t in p["ticker_mentions"]:
            if t not in tickers:
                tickers.append(t)
    shown = ", ".join(tickers[:5]) + (f" +{len(tickers) - 5}" if len(tickers) > 5 else "")
    sources = {p.get("source", "truth_social") for p in posts}
    if sources == {"news"}:
        title = f"🇺🇸 Trump on {shown} (via news)"
    elif sources == {"truth_social"}:
        title = f"🇺🇸 Trump named {shown} on Truth Social"
    else:
        title = f"🇺🇸 Trump on the tape: {shown}"

    lines: list[str] = []
    for p in posts:
        chips: list[str] = []
        for t in p["ticker_mentions"]:
            row = rows_by_ticker.get(t)
            pct = (row or {}).get("pct_1d")
            if pct is not None:
                chips.append(f"**{t}** {pct:+.1f}%")
            else:
                chips.append(f"**{t}**")
        excerpt = _clip((p.get("text") or "").replace("\n", " ").strip(), 60)
        line = " ".join(chips) + f' · "{excerpt}"'
        meta = []
        when = _rel_time(p.get("ts"), now)
        if when:
            meta.append(when)
        meta.append("via news" if p.get("source") == "news" else "Truth Social")
        line += " · " + " · ".join(meta)
        lines.append(line)

    # The /political route was killed (redirects to /); deep-link to the
    # ticker page when exactly one name was mentioned, else the site root.
    link = f"{_SITE_URL}/t/{tickers[0]}" if len(tickers) == 1 else _SITE_URL
    return {
        "type": "trump_pulse",
        "title": title,
        "body_md": "\n".join(lines),
        "link": link,
    }


def notify_fresh_mentions(payload: dict, rows: list[dict],
                          now: datetime | None = None) -> int:
    """Ping Feishu for NEW Trump stock mentions. Dedupes by post URL and only
    considers posts within the recency window. Returns cards sent (0 or 1)."""
    now = now or datetime.now(timezone.utc)
    candidates = list(payload.get("truth_posts", [])) + list(payload.get("news_posts", []))
    mention_posts = [p for p in candidates if p.get("ticker_mentions") and p.get("url")]
    if not mention_posts:
        return 0

    notified = _load_notified()
    notified_set = set(notified)
    cutoff = (now - timedelta(hours=_NOTIFY_RECENCY_HOURS)).isoformat()

    fresh: list[dict] = []
    for p in mention_posts:
        url = p["url"]
        if url in notified_set:
            continue
        notified.append(url)          # mark processed regardless of recency
        notified_set.add(url)
        ts = p.get("ts") or ""
        # Compare on the YYYY-MM-DDTHH:MM prefix to dodge offset-format mismatch.
        if ts and ts[:16] < cutoff[:16]:
            continue                  # too old — seen, but don't ping
        fresh.append(p)

    _save_notified(notified)
    if not fresh:
        return 0

    fresh = fresh[:_NOTIFY_MAX_POSTS]
    rows_by_ticker = {r["ticker"]: r for r in rows}
    alert = _build_mention_alert(fresh, rows_by_ticker, now)

    from scanner.alerts import feishu
    sent = feishu.send(alert)
    log.info("Trump notify: %d fresh mention post(s), Feishu %s",
             len(fresh), "sent" if sent else "dry-run/failed")
    return 1 if sent else 0
