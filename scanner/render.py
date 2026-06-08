"""Write scan + delta + news output to data/*.json for the web app to consume."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from scanner import config, staleness, universe
from scanner.windows import Window

log = logging.getLogger(__name__)

SCAN_FILE = config.DATA_DIR / "scan.json"
NEWS_FILE = config.DATA_DIR / "news.json"
PREDICTIONS_FILE = config.DATA_DIR / "predictions.json"


def _tier_for(memberships: list[str]) -> str:
    """Heuristic size tier based on index membership (proxy for market cap)."""
    if "ndx" in memberships:
        return "mega"  # NDX-100 is dominated by mega-cap tech
    if "sp500" in memberships:
        return "large"
    return "midsmall"


def enrich_rows(
    rows: list[dict],
    syntheses_by_ticker: dict[str, dict] | None = None,
    news_count_by_ticker: dict[str, int] | None = None,
    snapshots_by_ticker: dict[str, dict] | None = None,
    intraday_by_ticker: dict[str, dict] | None = None,
) -> list[dict]:
    """Attach tier / sector / snapshot / intraday / synthesis / caution to each
    scan row. Returns new dicts; the input rows are left untouched. Split out
    of write_scan so callers can score recommendations off the enriched rows."""
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
        # Late-entry / chase-risk score (computed from the enriched row)
        level, reasons = staleness.compute(out)
        if level != "none":
            out["caution_level"] = level
            out["caution_reasons"] = reasons
        enriched_rows.append(out)
    return enriched_rows


def write_scan(
    enriched_rows: list[dict],
    window: Window,
    now: datetime,
    universe_size: int,
    recommendations: dict | None = None,
) -> None:
    """Write data/scan.json from rows already enriched by enrich_rows()."""
    recommendations = recommendations or {"longs": [], "shorts": []}
    payload = {
        "generated_at": now.isoformat(),
        "window": window.value,
        "universe_size": universe_size,
        "row_count": len(enriched_rows),
        "synthesized_count": sum(1 for r in enriched_rows if r.get("synthesis")),
        "recommendations": recommendations,
        "rows": enriched_rows,
    }
    SCAN_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Wrote %d rows (%d with synthesis, %d long / %d short picks) to %s",
        len(enriched_rows),
        payload["synthesized_count"],
        len(recommendations.get("longs", [])),
        len(recommendations.get("shorts", [])),
        SCAN_FILE,
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


def write_predictions(
    events: list[dict],
    predictions: list[dict],
    now: datetime,
) -> None:
    """Write data/predictions.json — the ripple tier's forward second-order calls
    (read by the /predictions page + the dashboard's 'Ahead of the move' section).
    `predictions` is the flattened per-ticker list (freshest first); `events`
    keeps the per-story analysis for the event view + audit."""
    fresh = sum(1 for p in predictions if p.get("priced_in") == "no")
    payload = {
        "generated_at": now.isoformat(),
        "event_count": len(events),
        "prediction_count": len(predictions),
        "not_yet_priced_in": fresh,
        "events": events,
        "predictions": predictions,
    }
    PREDICTIONS_FILE.write_text(json.dumps(payload, indent=2))
    log.info(
        "Wrote predictions.json: %d events → %d predictions (%d not yet priced in)",
        len(events), len(predictions), fresh,
    )
