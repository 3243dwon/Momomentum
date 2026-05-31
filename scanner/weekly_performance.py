"""Weekly classification performance tracking.

Mirrors scanner.performance for the Saturday weekly run. Each `real_momentum`
/ `fakeout` / `unclear` call gets logged with the week-close entry price; on
subsequent weekly runs we evaluate forward returns at 2-week / 4-week / 8-week
horizons. The roll-up answers "does the classifier actually predict?" — same
analysis pattern as the alert/recommendation buckets.

Directional hit logic — a "hit" is a *correct directional call*:
  - real_momentum  → expect continuation (forward return > 0)
  - fakeout        → expect fade (forward return < -2%, leaving slack for noise)
  - unclear        → unpredicted; never counts as a hit (but tracked so we can
                     see whether 'unclear' picks are random vs systematically
                     positive/negative).

Reads from cache/weekly_classifications_log.jsonl, writes the rollup to
data/weekly_performance.json.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scanner import config

log = logging.getLogger(__name__)

WEEKLY_LOG = config.CACHE_DIR / "weekly_classifications_log.jsonl"
WEEKLY_PERFORMANCE_FILE = config.DATA_DIR / "weekly_performance.json"

RETENTION_DAYS = 90       # cover the longest horizon (~56d) with cushion
HORIZONS_DAYS = [14, 28, 56]  # 2w / 4w / 8w forward windows
FADE_THRESHOLD_PCT = -2.0  # fakeout "hit" requires at least this much downside


# --- I/O helpers (intentionally mirror performance.py) ------------------------

def _read_entries(path: Path = WEEKLY_LOG) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def _write_entries(entries: list[dict], path: Path = WEEKLY_LOG) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    entries = [e for e in entries if e["ts"] >= cutoff]
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _is_hit(classification: str, return_pct: float) -> bool | None:
    """Return True/False if the classification made a directional call that
    is now confirmed/disconfirmed by forward return; None for 'unclear'
    (no directional bet, not a hit/miss)."""
    if classification == "real_momentum":
        return return_pct > 0
    if classification == "fakeout":
        return return_pct < FADE_THRESHOLD_PCT
    return None


# --- Logging ------------------------------------------------------------------

def log_weekly_classifications(analyses: list[dict], now: datetime,
                                regime: dict | None = None) -> None:
    """Append this week's classifications to the log.

    `analyses` is the list returned by scanner.weekly.run_weekly(). Each entry
    has shape {ticker, event_count, heuristic_classification, metrics: {...,
    week_close}, analysis: {classification, prediction, prediction_confidence}}.
    We use the LLM `analysis.classification` if present (Opus call succeeded),
    falling back to the heuristic. Entry price = metrics.week_close.
    """
    if not analyses:
        return
    new_entries: list[dict] = []
    for a in analyses:
        ticker = a.get("ticker")
        metrics = a.get("metrics") or {}
        entry_price = metrics.get("week_close")
        if not ticker or not entry_price:
            continue

        opus = a.get("analysis") or {}
        classification = opus.get("classification") or a.get("heuristic_classification") or "unclear"
        prediction = opus.get("prediction")
        confidence = opus.get("prediction_confidence")

        entry = {
            "ts": now.astimezone(timezone.utc).isoformat(),
            "ticker": ticker,
            "classification": classification,
            "prediction": prediction,
            "prediction_confidence": confidence,
            "heuristic_classification": a.get("heuristic_classification"),
            "price_at_classification": entry_price,
            "metrics": metrics,
            "evaluations": {},
        }
        if regime:
            entry["regime"] = regime
        new_entries.append(entry)

    if new_entries:
        with open(WEEKLY_LOG, "a") as f:
            for e in new_entries:
                f.write(json.dumps(e) + "\n")
        log.info("Logged %d weekly classifications for performance tracking", len(new_entries))


# --- Evaluation ---------------------------------------------------------------

def _fetch_current_prices(alpaca_client, tickers: list[str]) -> dict[str, float]:
    """Same shape as performance._fetch_current_prices — kept duplicated rather
    than imported to avoid circular dependency and to let the two evaluators
    diverge later without coupling."""
    if not tickers:
        return {}
    try:
        from alpaca.data.requests import StockSnapshotRequest
        from alpaca.data.enums import DataFeed
        req = StockSnapshotRequest(symbol_or_symbols=tickers, feed=DataFeed.IEX)
        snaps = alpaca_client.get_stock_snapshot(req)
    except Exception as e:
        log.warning("Weekly performance Alpaca fetch failed: %s", e)
        return {}

    prices: dict[str, float] = {}
    for symbol, snap in snaps.items():
        try:
            for src in (
                getattr(snap, "latest_trade", None),
                getattr(snap, "minute_bar", None),
                getattr(snap, "daily_bar", None),
            ):
                if src is None:
                    continue
                p = getattr(src, "price", None) or getattr(src, "close", None)
                if p:
                    prices[symbol] = float(p)
                    break
        except Exception:
            pass
    return prices


def evaluate_pending(alpaca_client, now: datetime) -> None:
    """For each logged classification past a horizon without an eval, fetch
    current price and record signed return + hit flag."""
    if alpaca_client is None:
        return
    entries = _read_entries()
    pending: list[tuple[int, str, int]] = []
    for i, entry in enumerate(entries):
        try:
            entry_time = datetime.fromisoformat(entry["ts"])
        except Exception:
            continue
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        age_days = (now - entry_time).total_seconds() / 86400
        for h in HORIZONS_DAYS:
            if f"{h}d" in entry.get("evaluations", {}):
                continue
            if age_days < h:
                continue
            pending.append((i, entry["ticker"], h))

    if not pending:
        return

    prices = _fetch_current_prices(alpaca_client, sorted({t for _, t, _ in pending}))
    if not prices:
        return

    updated = 0
    for idx, ticker, h in pending:
        if ticker not in prices:
            continue
        entry = entries[idx]
        entry_price = entry.get("price_at_classification")
        if not entry_price:
            continue
        current = prices[ticker]
        return_pct = (current / entry_price - 1) * 100
        hit = _is_hit(entry.get("classification", "unclear"), return_pct)
        entry.setdefault("evaluations", {})[f"{h}d"] = {
            "price": round(current, 2),
            "return_pct": round(return_pct, 2),
            "hit": hit,
        }
        updated += 1

    if updated:
        _write_entries(entries)
        log.info("Evaluated %d pending weekly horizons", updated)


# --- Rollup -------------------------------------------------------------------

def compile_stats(now: datetime) -> dict:
    """Bucket by classification × confidence, compute hit rate + avg return."""
    entries = _read_entries()
    # 90-day window — covers all horizons (longest = 56d) + room for the
    # roll-up to cover at least one full eval cycle.
    cutoff = (now - timedelta(days=90)).isoformat()
    recent = [e for e in entries if e["ts"] >= cutoff]

    buckets: dict[str, dict] = {}
    for e in recent:
        cls = e.get("classification", "unclear")
        conf = e.get("prediction_confidence") or "na"
        key = f"{cls}__{conf}"
        bucket = buckets.setdefault(
            key,
            {
                "count": 0,
                "classification": cls,
                "confidence": conf,
                "horizons": {h: {"n": 0, "hits": 0, "directional_n": 0, "returns": []} for h in HORIZONS_DAYS},
            },
        )
        bucket["count"] += 1
        for h in HORIZONS_DAYS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            bucket["horizons"][h]["n"] += 1
            bucket["horizons"][h]["returns"].append(ev["return_pct"])
            # `hit` is None for 'unclear' — count in n (to know coverage) but
            # not in hit rate, which is meaningless without a directional call.
            if ev.get("hit") is not None:
                bucket["horizons"][h]["directional_n"] += 1
                if ev["hit"]:
                    bucket["horizons"][h]["hits"] += 1

    out: dict = {
        "generated_at": now.isoformat(),
        "window_days": 90,
        "total_classifications": len(recent),
        "horizons_days": HORIZONS_DAYS,
        "fade_threshold_pct": FADE_THRESHOLD_PCT,
        "per_bucket": {},
    }
    for key, stats in buckets.items():
        horizons = {}
        for h, hs in stats["horizons"].items():
            n = hs["n"]
            d_n = hs["directional_n"]
            horizons[f"{h}d"] = {
                "evaluated": n,
                "directional_evaluated": d_n,
                "hit_rate": round(hs["hits"] / d_n, 3) if d_n else None,
                "avg_return_pct": round(sum(hs["returns"]) / n, 2) if n else None,
            }
        out["per_bucket"][key] = {
            "classification": stats["classification"],
            "confidence": stats["confidence"],
            "count": stats["count"],
            "horizons": horizons,
        }

    WEEKLY_PERFORMANCE_FILE.write_text(json.dumps(out, indent=2))
    log.info(
        "Weekly performance stats: %d classifications in 90d, %d buckets",
        out["total_classifications"], len(out["per_bucket"]),
    )
    return out
