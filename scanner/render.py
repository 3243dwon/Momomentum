"""Write scan + delta + news output to data/*.json for the web app to consume."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from scanner import config, universe
from scanner.windows import Window

log = logging.getLogger(__name__)

SCAN_FILE = config.DATA_DIR / "scan.json"
NEWS_FILE = config.DATA_DIR / "news.json"


def _tier_for(memberships: list[str]) -> str:
    """Heuristic size tier based on index membership (proxy for market cap)."""
    if "ndx" in memberships:
        return "mega"  # NDX-100 is dominated by mega-cap tech
    if "sp500" in memberships:
        return "large"
    return "midsmall"


def write_scan(
    rows: list[dict],
    window: Window,
    now: datetime,
    universe_size: int,
    syntheses_by_ticker: dict[str, dict] | None = None,
    news_count_by_ticker: dict[str, int] | None = None,
    snapshots_by_ticker: dict[str, dict] | None = None,
    intraday_by_ticker: dict[str, dict] | None = None,
) -> None:
    syntheses_by_ticker = syntheses_by_ticker or {}
    news_count_by_ticker = news_count_by_ticker or {}
    snapshots_by_ticker = snapshots_by_ticker or {}
    intraday_by_ticker = intraday_by_ticker or {}
    tags_by_ticker = universe.load_tags()
    sectors_by_ticker = universe.load_sectors()

    enriched_rows = []
    for r in rows:
        out = dict(r)
        t = r["ticker"]
        out["news_count"] = news_count_by_ticker.get(t, 0)
        out["tier"] = _tier_for(tags_by_ticker.get(t, []))
        out["membership"] = tags_by_ticker.get(t, [])
        if t in sectors_by_ticker:
            out["sector"] = sectors_by_ticker[t]
        if t in snapshots_by_ticker:
            out["snapshot"] = snapshots_by_ticker[t]
        if t in intraday_by_ticker:
            out["intraday"] = intraday_by_ticker[t]
        if t in syntheses_by_ticker:
            out["synthesis"] = syntheses_by_ticker[t]
        enriched_rows.append(out)

    payload = {
        "generated_at": now.isoformat(),
        "window": window.value,
        "universe_size": universe_size,
        "row_count": len(enriched_rows),
        "synthesized_count": sum(1 for r in enriched_rows if r.get("synthesis")),
        "rows": enriched_rows,
    }
    SCAN_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Wrote %d rows (%d with synthesis) to %s",
        len(enriched_rows), payload["synthesized_count"], SCAN_FILE,
    )


def write_news(
    ticker_news: dict[str, list[dict]],
    macro_analyses: list[dict],
    now: datetime,
) -> None:
    payload = {
        "generated_at": now.isoformat(),
        "ticker_news": ticker_news,
        "macro_events": macro_analyses,
    }
    NEWS_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Wrote news.json: %d tickers with news, %d macro analyses",
        len(ticker_news), len(macro_analyses),
    )
