"""Data-access layer for the Momentum MCP server.

Reads the scanner's committed JSON in ``data/`` and reshapes it into compact,
LLM-friendly structures. There is deliberately **no MCP dependency** in this
module so the logic stays unit-testable on its own; ``server.py`` wraps these
functions as MCP tools.

Data location: ``$MOMENTUM_DATA_DIR`` if set, else the repo's ``data/`` dir
(this file lives in ``mcp/``, so ``../data``). The files are git-tracked, so a
``git pull`` (or a scanner run) is what makes the data fresh.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(
    os.environ.get("MOMENTUM_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data")
)

# Files surfaced in the freshness summary (skip the big static ones: universe,
# company_aliases, *_state).
_BRAIN_FILES = [
    "scan", "briefing", "news", "serenity", "predictions", "deals", "ledger",
    "weekly", "performance", "recommendation_performance", "prediction_performance",
    "desk_performance", "political",
]


class DataUnavailable(Exception):
    """A requested data file is missing — usually means run the scanner / git pull."""


def _load(name: str) -> dict:
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        raise DataUnavailable(
            f"{name}.json not found in {DATA_DIR}. Run the scanner or `git pull` to populate it."
        )
    return json.loads(path.read_text())


def _try_load(name: str) -> dict | None:
    try:
        return _load(name)
    except DataUnavailable:
        return None


def _age_min(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - t).total_seconds() / 60, 1)
    except (ValueError, TypeError):
        return None


def _fresh(d: dict) -> dict:
    g = d.get("generated_at")
    return {"generated_at": g, "age_minutes": _age_min(g)}


def _norm(ticker: str) -> str:
    return ticker.upper().strip().lstrip("$")


# ── shapers: trim verbose records to what an LLM actually needs ──────────────

def _shape_row(r: dict) -> dict:
    return {
        "ticker": r.get("ticker"),
        "price": r.get("price"),
        "pct_1d": r.get("pct_1d"),
        "pct_5d": r.get("pct_5d"),
        "rel_volume": r.get("rel_volume"),
        "rsi_14": r.get("rsi_14"),
        "macd_cross": r.get("macd_cross"),
        "flags": r.get("flags") or [],
        "sector": r.get("sector"),
        "tier": r.get("tier"),
        "news_count": r.get("news_count"),
    }


def _shape_rec(r: dict) -> dict:
    desk = r.get("desk") or {}
    return {
        "direction": r.get("direction"),
        "score": r.get("score"),
        "horizon": r.get("horizon"),
        "reasons": r.get("reasons") or [],
        "cautions": r.get("cautions") or [],
        "levels": r.get("levels"),
        "desk_decision": desk.get("decision"),
        "desk_size": desk.get("size"),
        "desk_agreement": desk.get("agreement"),
        "desk_rationale": desk.get("rationale"),
        "desk_plan": desk.get("plan"),
    }


def _shape_news(n: dict) -> dict:
    return {
        "title": n.get("title"),
        "source": n.get("source") or n.get("publisher"),
        "url": n.get("url"),
        "published_at": n.get("published_at"),
        "impact": n.get("impact"),
        "type": n.get("type"),
    }


def _shape_tweet(tw: dict) -> dict:
    return {
        "summary": tw.get("summaryEn"),
        "text": tw.get("text"),
        "stance": tw.get("stance"),
        "tickers": tw.get("tickers") or [],
        "url": tw.get("url"),
        "created_at": tw.get("createdAt"),
        "metrics": tw.get("metrics"),
    }


def _shape_ledger(e: dict) -> dict:
    return {
        "ts": e.get("ts"),
        "kind": e.get("kind"),
        "type": e.get("type"),
        "ticker": e.get("ticker"),
        "direction": e.get("direction"),
        "price": e.get("price"),
        "thesis": e.get("thesis"),
        "outcomes": e.get("outcomes"),
        "status": e.get("status"),
    }


def _shape_weekly(a: dict) -> dict:
    analysis = a.get("analysis") or {}
    return {
        "ticker": a.get("ticker"),
        "classification": analysis.get("classification") or a.get("heuristic_classification"),
        "prediction": analysis.get("prediction"),
        "prediction_confidence": analysis.get("prediction_confidence"),
        "reasoning": analysis.get("classification_reasoning"),
        "next_weeks": analysis.get("prediction_rationale"),
        "metrics": a.get("metrics"),
    }


# ── tools ───────────────────────────────────────────────────────────────────

def status() -> dict:
    """Snapshot of the scanner right now: freshness, market regime, counts,
    the latest briefing headline, and the age of every brain file."""
    scan = _load("scan")
    regime = scan.get("regime") or {}
    briefing = _try_load("briefing")
    freshness = {}
    for name in _BRAIN_FILES:
        d = _try_load(name)
        freshness[name] = _age_min(d.get("generated_at")) if isinstance(d, dict) else None
    return {
        "scan": {
            **_fresh(scan),
            "window": scan.get("window"),
            "regime": regime.get("label"),
            "spy_pct_1d": regime.get("spy_pct_1d"),
            "qqq_pct_1d": regime.get("qqq_pct_1d"),
            "row_count": scan.get("row_count"),
            "universe_size": scan.get("universe_size"),
        },
        "briefing_headline": briefing.get("headline") if briefing else None,
        "data_freshness_minutes": freshness,
        "data_dir": str(DATA_DIR),
    }


def get_ticker(ticker: str) -> dict:
    """The full picture on one name, cross-referenced across every source:
    scan momentum/indicators, the desk's take, recent news, Serenity (Chinese-X)
    mentions, ripple predictions, the weekly verdict, and the call ledger."""
    t = _norm(ticker)
    scan = _load("scan")
    row = next((r for r in scan.get("rows", []) if r.get("ticker") == t), None)

    rec = None
    recs = scan.get("recommendations") or {}
    for side in ("longs", "shorts"):
        for r in recs.get(side, []):
            if r.get("ticker") == t:
                rec = _shape_rec(r)

    news = _try_load("news") or {}
    news_items = [_shape_news(n) for n in (news.get("ticker_news", {}).get(t) or [])[:8]]

    seren = _try_load("serenity") or {}
    serenity = [
        _shape_tweet(tw) for tw in seren.get("tweets", []) if t in (tw.get("tickers") or [])
    ][:8]

    pred = _try_load("predictions") or {}
    predictions = [
        p for p in pred.get("predictions", [])
        if _norm(p.get("ticker", "")) == t or _norm(p.get("trigger_ticker", "")) == t
    ]

    weekly = _try_load("weekly") or {}
    weekly_entry = next(
        (a for a in weekly.get("analyses", []) if _norm(a.get("ticker", "")) == t), None
    )

    ledger = _try_load("ledger") or {}
    ledger_history = [
        _shape_ledger(e) for e in ledger.get("entries", []) if _norm(e.get("ticker", "")) == t
    ][:20]

    found = any([row, rec, news_items, serenity, predictions, weekly_entry, ledger_history])
    if not found:
        return {"ticker": t, "found": False, "note": "No coverage of this ticker in the current data."}

    return {
        "ticker": t,
        "found": True,
        "scan": _shape_row(row) if row else None,
        "desk_take": rec,
        "news": news_items,
        "serenity": serenity,
        "predictions": predictions,
        "weekly_verdict": _shape_weekly(weekly_entry) if weekly_entry else None,
        "ledger_history": ledger_history,
    }


def top_movers(limit: int = 10, direction: str = "both") -> dict:
    """The biggest movers in the latest scan, ranked by absolute 1-day move.
    direction: 'up', 'down', or 'both'."""
    scan = _load("scan")
    rows = [r for r in scan.get("rows", []) if r.get("pct_1d") is not None]
    if direction == "up":
        rows = [r for r in rows if r["pct_1d"] > 0]
    elif direction == "down":
        rows = [r for r in rows if r["pct_1d"] < 0]
    rows.sort(key=lambda r: abs(r["pct_1d"]), reverse=True)
    return {
        **_fresh(scan),
        "window": scan.get("window"),
        "regime": (scan.get("regime") or {}).get("label"),
        "movers": [_shape_row(r) for r in rows[: max(1, min(limit, 100))]],
    }


def desk_recommendations() -> dict:
    """The desk's current long and short picks — score, levels, the multi-agent
    decision (take/pass) and the plan behind each."""
    scan = _load("scan")
    recs = scan.get("recommendations") or {}
    shape = lambda r: {"ticker": r.get("ticker"), **_shape_rec(r)}
    return {
        **_fresh(scan),
        "longs": [shape(r) for r in recs.get("longs", [])],
        "shorts": [shape(r) for r in recs.get("shorts", [])],
    }


def query_ledger(
    ticker: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> dict:
    """The accountability ledger — every dispatched call and how it graded.
    Filters: ticker, status (pending/hit/miss/untracked), kind (alert/pick/prediction)."""
    led = _load("ledger")
    entries = led.get("entries", [])
    if ticker:
        t = _norm(ticker)
        entries = [e for e in entries if _norm(e.get("ticker", "")) == t]
    if status:
        entries = [e for e in entries if e.get("status") == status]
    if kind:
        entries = [e for e in entries if e.get("kind") == kind]
    entries = sorted(entries, key=lambda e: e.get("ts", ""), reverse=True)
    return {
        **_fresh(led),
        "window_days": led.get("window_days"),
        "match_count": len(entries),
        "entries": [_shape_ledger(e) for e in entries[: max(1, min(limit, 200))]],
    }


def get_serenity(ticker: str | None = None, limit: int = 30) -> dict:
    """The Serenity feed — synthesized Chinese-X (Twitter) market chatter, with
    English summaries, stance, and tagged tickers. Optionally filter to a ticker."""
    s = _load("serenity")
    tweets = s.get("tweets", [])
    if ticker:
        t = _norm(ticker)
        tweets = [tw for tw in tweets if t in (tw.get("tickers") or [])]
    return {
        **_fresh(s),
        "match_count": len(tweets),
        "tweets": [_shape_tweet(tw) for tw in tweets[: max(1, min(limit, 100))]],
    }


def get_predictions() -> dict:
    """Ripple forward-predictions: popular-stock catalysts and the second-order
    names they should move, with mechanism and whether it's priced in yet."""
    p = _load("predictions")
    return {
        **_fresh(p),
        "event_count": p.get("event_count"),
        "prediction_count": p.get("prediction_count"),
        "not_yet_priced_in": p.get("not_yet_priced_in"),
        "predictions": p.get("predictions", []),
        "events": p.get("events", []),
    }


def get_briefing() -> dict:
    """The latest one-read briefing: headline, market state, actionable calls,
    what to watch, and what changed since the last scan."""
    b = _load("briefing")
    return {
        **_fresh(b),
        "window": b.get("window"),
        "headline": b.get("headline"),
        "market_state": b.get("market_state"),
        "actions": b.get("actions"),
        "watch": b.get("watch"),
        "changed": b.get("changed"),
        "caveats": b.get("caveats"),
    }


def signal_performance() -> dict:
    """The signal scoreboard — for each signal class, how often its directional
    call followed through, by horizon. The track record behind the conviction."""
    p = _load("performance")
    out = {}
    for kind, stats in (p.get("per_type") or {}).items():
        horizons = {}
        for h, hs in (stats.get("horizons") or {}).items():
            if not isinstance(hs, dict):
                continue
            horizons[h] = {
                "hit_rate": hs.get("hit_rate"),
                "evaluated": hs.get("evaluated"),
                "avg_return_pct": hs.get("avg_return_pct"),
            }
        out[kind] = {"count": stats.get("count"), "horizons": horizons}
    return {
        **_fresh(p),
        "window_days": p.get("window_days"),
        "total_alerts": p.get("total_alerts"),
        "slippage_round_trip_pct": p.get("slippage_round_trip_pct"),
        "per_type": out,
    }


def get_deals(limit: int = 20) -> dict:
    """Deal flow: high-impact catalysts on popular names and the second-order
    ripple calls each one sets up."""
    d = _load("deals")
    deals = d.get("deals", [])
    return {
        **_fresh(d),
        "window_days": d.get("window_days"),
        "deal_count": d.get("deal_count"),
        "deals": deals[: max(1, min(limit, 50))],
    }
