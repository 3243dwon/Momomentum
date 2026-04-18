"""Event accumulator for the weekly summary.

Each scan appends 'notable' momentum events to data/weekly_events.json.
The weekly analyzer (scanner/weekly.py) reads this on Saturday and feeds
it to Opus for real-vs-fake classification + forward predictions.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scanner import config

log = logging.getLogger(__name__)

EVENTS_FILE = config.DATA_DIR / "weekly_events.json"
RETENTION_DAYS = 9  # keep a little beyond 7 for Sat analysis + buffer
CAP = 20000  # safety cap in case a hot week generates thousands of events


def _load() -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    try:
        return json.loads(EVENTS_FILE.read_text())
    except Exception:
        return []


def _save(events: list[dict]) -> None:
    EVENTS_FILE.write_text(json.dumps(events, indent=2))


def _notable(row: dict, watchlist: set[str]) -> bool:
    """Should this row be logged as an event worth analyzing later?"""
    flags = row.get("flags", []) or []
    pct = abs(row.get("pct_1d") or 0)
    if row["ticker"] in watchlist and pct >= 1.0:
        return True
    if "big_move" in flags or "unusual_volume" in flags:
        return True
    return False


def record(
    rows: list[dict],
    ticker_news: dict[str, list[dict]],
    syntheses: dict[str, dict],
    window: str,
    now: datetime,
    watchlist: set[str],
) -> None:
    """Append notable rows from the current scan as events."""
    events = _load()
    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
    events = [e for e in events if e["ts"] >= cutoff]

    for r in rows:
        t = r["ticker"]
        if not _notable(r, watchlist):
            continue
        synth = syntheses.get(t)
        events.append(
            {
                "ts": now.isoformat(),
                "ticker": t,
                "price": r.get("price"),
                "pct_1d": r.get("pct_1d"),
                "pct_5d": r.get("pct_5d"),
                "volume": r.get("volume"),
                "rel_volume": r.get("rel_volume"),
                "rsi_14": r.get("rsi_14"),
                "flags": r.get("flags", []),
                "tier": r.get("tier"),
                "news_count": r.get("news_count", 0),
                "has_news": bool(ticker_news.get(t)),
                "synthesis_verdict": synth.get("verdict") if synth else None,
                "synthesis_confidence": synth.get("confidence") if synth else None,
                "synthesis_summary": synth.get("summary") if synth else None,
                "window": window,
                "intraday": r.get("intraday"),
                "snapshot": r.get("snapshot"),
            }
        )

    if len(events) > CAP:
        events = events[-CAP:]
    _save(events)
    log.info("Weekly events log: %d total entries (cutoff %s)", len(events), cutoff[:10])


def load_week(now: datetime, days: int = 7) -> list[dict]:
    """Load events from the last N days."""
    events = _load()
    cutoff = (now - timedelta(days=days)).isoformat()
    return [e for e in events if e["ts"] >= cutoff]
