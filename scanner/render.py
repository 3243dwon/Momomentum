"""Write scan + delta + news output to data/*.json for the web app to consume."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from scanner import config, staleness, universe
from scanner.windows import Window

log = logging.getLogger(__name__)

SCAN_FILE = config.DATA_DIR / "scan.json"
NEWS_FILE = config.DATA_DIR / "news.json"
PREDICTIONS_FILE = config.DATA_DIR / "predictions.json"
# id → created_at map so a story re-emitted across scans keeps its ORIGINAL
# created_at (predictions are regenerated fresh each scan). Cache-only.
PREDICTION_CREATED_AT_FILE = config.CACHE_DIR / "prediction_created_at.json"
_PREDICTION_CREATED_AT_RETENTION_DAYS = 45


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
    regime: dict | None = None,
) -> None:
    """Write data/scan.json from rows already enriched by enrich_rows().

    `regime` is the dict main.py already computed via regime.compute() —
    passed through (never recomputed here). May be {} on Alpaca failure;
    the web handles absence."""
    recommendations = recommendations or {"longs": [], "shorts": []}
    payload = {
        "generated_at": now.isoformat(),
        "window": window.value,
        "universe_size": universe_size,
        "row_count": len(enriched_rows),
        "synthesized_count": sum(1 for r in enriched_rows if r.get("synthesis")),
        "regime": regime or {},
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


def _prediction_id(p: dict) -> str:
    """Stable per-story-per-call identity: same story re-emitted across scans
    (same source news + ticker + direction) maps to the same id."""
    src = next(iter(p.get("source_news_ids") or []), None) or p.get("event_summary", "")
    raw = f"{p.get('trigger_ticker')}|{src}|{p.get('ticker')}|{p.get('direction')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _stamp_created_at(predictions: list[dict], now: datetime) -> None:
    """Attach created_at (ISO, first-generation time) to each prediction.
    Re-emissions keep the original timestamp via a small cache-side map.
    Fail-soft: on any cache error every prediction is stamped with `now`."""
    created_map: dict[str, str] = {}
    try:
        if PREDICTION_CREATED_AT_FILE.exists():
            loaded = json.loads(PREDICTION_CREATED_AT_FILE.read_text())
            if isinstance(loaded, dict):
                created_map = {str(k): str(v) for k, v in loaded.items()}
    except Exception as e:
        log.warning("Prediction created_at map unreadable (%s); restamping", e)

    now_iso = now.isoformat()
    for p in predictions:
        pid = _prediction_id(p)
        p["created_at"] = created_map.get(pid) or now_iso
        created_map[pid] = p["created_at"]

    # Prune entries past retention so the map can't grow unbounded.
    cutoff = datetime.now(timezone.utc) - timedelta(days=_PREDICTION_CREATED_AT_RETENTION_DAYS)
    pruned: dict[str, str] = {}
    for k, v in created_map.items():
        try:
            ts = datetime.fromisoformat(v)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                pruned[k] = v
        except Exception:
            continue
    try:
        PREDICTION_CREATED_AT_FILE.write_text(json.dumps(pruned, indent=2))
    except Exception as e:
        log.warning("Prediction created_at map not persisted: %s", e)


def write_predictions(
    events: list[dict],
    predictions: list[dict],
    now: datetime,
) -> None:
    """Write data/predictions.json — the ripple tier's forward second-order calls
    (read by the /predictions page + the dashboard's 'Ahead of the move' section).
    `predictions` is the flattened per-ticker list (freshest first); `events`
    keeps the per-story analysis for the event view + audit."""
    _stamp_created_at(predictions, now)
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
