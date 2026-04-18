"""Tier-0 routing: decides which tickers earn the cost of news fetch + LLM analysis.

The router cuts ~2,500 tickers down to ~50-200 per scan based on rule-based
signals. This is the cost lever that makes a 3-tier LLM affordable: only
tickers passing this filter ever reach Haiku/Sonnet.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from scanner import config
from scanner.windows import Window

log = logging.getLogger(__name__)

WATCHLIST_FILE = config.DATA_DIR / "watchlist.json"


def load_watchlist() -> set[str]:
    if not WATCHLIST_FILE.exists():
        return set()
    try:
        return set(json.loads(WATCHLIST_FILE.read_text()).get("tickers", []))
    except Exception:
        return set()


def route(rows: list[dict], deltas: dict, window: Window) -> tuple[list[str], list[str]]:
    """Return (route_to_news, watchlist_only_tickers).

    route_to_news = the tickers we'll fetch news for AND ask Haiku/Sonnet about.
    watchlist_only_tickers = pinned in UI but no LLM treatment unless they also
                             passed a real signal.
    """
    watchlist = load_watchlist()

    pct_threshold = (
        config.PCT_MOVE_THRESHOLD_RTH
        if window == Window.RTH
        else config.PCT_MOVE_THRESHOLD_AH
    )

    by_ticker = {r["ticker"]: r for r in rows}
    delta_set = set(deltas.get("new_top20_entrants", []))
    delta_set.update(j["ticker"] for j in deltas.get("rank_jumps", []))
    delta_set.update(deltas.get("momentum_accel", []))

    routed: set[str] = set()
    for r in rows:
        t = r["ticker"]
        pct = r.get("pct_1d") or 0
        rel_vol = r.get("rel_volume") or 0

        if abs(pct) >= pct_threshold:
            routed.add(t)
        elif rel_vol >= config.REL_VOLUME_THRESHOLD:
            routed.add(t)
        elif t in delta_set:
            routed.add(t)
        elif t in watchlist and abs(pct) >= 1.5:
            routed.add(t)

    log.info(
        "Tier 0 routing: %d/%d tickers routed to news+LLM",
        len(routed), len(rows),
    )
    return sorted(routed), sorted(watchlist)
