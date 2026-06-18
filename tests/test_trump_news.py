"""Test the Trump news-comment source on the REAL headlines we missed.

Mocks the Google News RSS fetch so it runs offline. Run:
  .venv/bin/python tests/test_trump_news.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import trump_pulse

PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


# Real Google-News-style RSS: titles carry a " - Publisher" suffix.
FAKE_RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Trump Says U.S. Will Take 10% Stake in Intel as Nvidia, Musk, and Apple Agree to Chip Partnerships - Binance</title>
<link>https://news.google.com/x1</link><pubDate>Wed, 17 Jun 2026 13:00:00 +0000</pubDate><description>x</description></item>
<item><title>Trump says Apple to work with Intel to manufacture chips in US - Reuters</title>
<link>https://news.google.com/x2</link><pubDate>Wed, 17 Jun 2026 13:30:00 +0000</pubDate><description>x</description></item>
<item><title>Trump Claims US Chip Industry Will Revive - Intellectia AI</title>
<link>https://news.google.com/x3</link><pubDate>Wed, 17 Jun 2026 09:00:00 +0000</pubDate><description>x</description></item>
</channel></rss>"""


def test_extraction():
    print("test_trump_news (real missed headlines)")
    universe = {"INTC", "NVDA", "AAPL", "TSLA"}
    aliases = trump_pulse._load_aliases()  # the real data/company_aliases.json
    check("aliases loaded (intel/apple/nvidia present)",
          "INTC" in aliases and "AAPL" in aliases and "NVDA" in aliases)

    orig = trump_pulse._fetch
    trump_pulse._fetch = lambda url, headers=None: SimpleNamespace(status_code=200, text=FAKE_RSS)
    try:
        posts = trump_pulse.fetch_trump_news(universe, aliases, datetime(2026, 6, 17, 14, tzinfo=timezone.utc))
    finally:
        trump_pulse._fetch = orig

    by_url = {p["url"]: p for p in posts}
    check("kept 2 ticker-naming headlines, dropped the no-ticker one", len(posts) == 2)

    p1 = by_url.get("https://news.google.com/x1")
    check("Intel-stake headline found", p1 is not None)
    if p1:
        m = set(p1["ticker_mentions"])
        check("extracts INTC + NVDA + AAPL", {"INTC", "NVDA", "AAPL"} <= m)
        check("publisher ' - Binance' stripped from text", "Binance" not in p1["text"])
        check("tagged source=news", p1["source"] == "news")
        check("has ISO ts", (p1["ts"] or "").startswith("2026-06-17"))

    p2 = by_url.get("https://news.google.com/x2")
    check("Apple/Intel headline found", p2 is not None)
    if p2:
        check("extracts AAPL + INTC", {"AAPL", "INTC"} <= set(p2["ticker_mentions"]))

    check("no-ticker 'Chip Industry Will Revive' dropped",
          "https://news.google.com/x3" not in by_url)


def test_notify_includes_news():
    print("test_notify (news comment fires a fresh alert)")
    sent = {}
    import scanner.alerts.feishu as feishu
    orig_send = feishu.send
    orig_notified_load = trump_pulse._load_notified
    orig_notified_save = trump_pulse._save_notified
    feishu.send = lambda alert: sent.update(alert) or True
    trump_pulse._load_notified = lambda: []
    trump_pulse._save_notified = lambda urls: None
    try:
        now = datetime(2026, 6, 17, 14, tzinfo=timezone.utc)
        payload = {
            "truth_posts": [],
            "news_posts": [{
                "ts": "2026-06-17T13:30:00+00:00",
                "text": "Trump says Apple to work with Intel to manufacture chips in US",
                "url": "https://news.google.com/x2",
                "ticker_mentions": ["AAPL", "INTC"],
                "source": "news",
            }],
        }
        rows = [{"ticker": "INTC", "pct_1d": 6.2}, {"ticker": "AAPL", "pct_1d": 1.1}]
        n = trump_pulse.notify_fresh_mentions(payload, rows, {"INTC"}, now)
    finally:
        feishu.send = orig_send
        trump_pulse._load_notified = orig_notified_load
        trump_pulse._save_notified = orig_notified_save

    check("one card sent", n == 1)
    check("title flags via-news provenance", "via news" in sent.get("title", ""))
    check("body names INTC", "INTC" in sent.get("body_md", ""))


if __name__ == "__main__":
    test_extraction()
    test_notify_includes_news()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
