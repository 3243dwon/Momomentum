"""Alert performance tracking.

Every dispatched alert is logged with the alert-time price + direction.
On each scan, entries past their evaluation horizon (1d / 3d / 5d) get a
current-price lookup via Alpaca and a signed-return computed in the direction
of the original alert.

Stats are compiled over a 30-day trailing window and written to
data/performance.json for the web app.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scanner import config

log = logging.getLogger(__name__)

ALERTS_LOG = config.CACHE_DIR / "alerts_log.jsonl"       # gitignored + cached across runs
PERFORMANCE_FILE = config.DATA_DIR / "performance.json"  # aggregates only; web UI reads it
RECS_LOG = config.CACHE_DIR / "recommendations_log.jsonl"
RECOMMENDATION_PERFORMANCE_FILE = config.DATA_DIR / "recommendation_performance.json"
DESK_PERFORMANCE_FILE = config.DATA_DIR / "desk_performance.json"

RETENTION_DAYS = 45
HORIZONS = [1, 3, 5]  # days
HIGH_SCORE = 7  # recommendation score >= this is bucketed as a high-conviction pick


def _read_entries(path: Path = ALERTS_LOG) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def _write_entries(entries: list[dict], path: Path = ALERTS_LOG) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    entries = [e for e in entries if e["ts"] >= cutoff]
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _extract_features(row: dict) -> dict:
    """Snapshot the per-row signals we'll regress forward returns against
    later. Kept compact so the .jsonl stays readable; nullables passed through
    as-is so missing signals don't get confused with zero."""
    synth = row.get("synthesis") or {}
    intraday = row.get("intraday") or {}
    snapshot = row.get("snapshot") or {}
    return {
        "pct_1d": row.get("pct_1d"),
        "pct_5d": row.get("pct_5d"),
        "rel_volume": row.get("rel_volume"),
        "rsi_14": row.get("rsi_14"),
        "macd_cross": row.get("macd_cross"),
        "macd_hist": row.get("macd_hist"),
        "above_vwap": intraday.get("above_vwap"),
        "gap_pct": snapshot.get("gap_pct"),
        "caution_level": row.get("caution_level"),
        "has_synthesis": bool(synth),
        "verdict": synth.get("verdict") if synth else None,
        "confidence": synth.get("confidence") if synth else None,
        "news_count": row.get("news_count"),
        "tier": row.get("tier"),
        "sector": row.get("sector"),
        "flags": row.get("flags") or [],
    }


def log_alerts(alerts: list[dict], rows: list[dict], now: datetime,
                regime: dict | None = None) -> None:
    """Append dispatched alerts to the log. Macro alerts (no ticker) are skipped.

    `regime` (optional) is the output of scanner.regime.compute() — stored on
    each entry so future analysis can split hit rates by regime label.
    """
    by_ticker = {r["ticker"]: r for r in rows}
    existing = _read_entries()
    new_entries = []
    for alert in alerts:
        t = alert.get("ticker")
        if not t:
            continue
        row = by_ticker.get(t)
        if not row or row.get("price") is None:
            continue
        pct = row.get("pct_1d") or 0
        entry = {
            "ts": now.astimezone(timezone.utc).isoformat(),
            "ticker": t,
            "type": alert.get("type", "unknown"),
            "price_at_alert": row["price"],
            "pct_1d_at_alert": pct,
            "direction": 1 if pct >= 0 else -1,
            "evaluations": {},
        }
        if regime:
            entry["regime"] = regime
        new_entries.append(entry)
    if new_entries:
        with open(ALERTS_LOG, "a") as f:
            for e in new_entries:
                f.write(json.dumps(e) + "\n")
        log.info("Logged %d alerts for performance tracking", len(new_entries))


def _fetch_current_prices(alpaca_client, tickers: list[str]) -> dict[str, float]:
    """Batch Alpaca snapshot → {ticker: latest price}. Empty on any failure."""
    if not tickers:
        return {}
    try:
        from alpaca.data.requests import StockSnapshotRequest
        from alpaca.data.enums import DataFeed
        req = StockSnapshotRequest(symbol_or_symbols=tickers, feed=DataFeed.IEX)
        snaps = alpaca_client.get_stock_snapshot(req)
    except Exception as e:
        log.warning("Performance evaluation Alpaca fetch failed: %s", e)
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


def _evaluate_log(alpaca_client, now: datetime, log_path: Path,
                  price_key: str, sign_fn) -> None:
    """For each entry in log_path past a horizon without an eval, fetch the
    current price and record a return signed by sign_fn(entry) (+1 / -1)."""
    if alpaca_client is None:
        return
    entries = _read_entries(log_path)
    pending: list[tuple[int, str, int]] = []
    for i, entry in enumerate(entries):
        try:
            entry_time = datetime.fromisoformat(entry["ts"])
        except Exception:
            continue
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        age_days = (now - entry_time).total_seconds() / 86400
        for h in HORIZONS:
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
        entry_price = entry.get(price_key)
        if not entry_price:
            continue
        current = prices[ticker]
        return_pct = (current / entry_price - 1) * 100
        signed = return_pct * sign_fn(entry)
        entry.setdefault("evaluations", {})[f"{h}d"] = {
            "price": round(current, 2),
            "return_pct": round(return_pct, 2),
            "signed_return_pct": round(signed, 2),
        }
        updated += 1

    if updated:
        _write_entries(entries, log_path)
        log.info("Evaluated %d pending %s horizons", updated, log_path.stem)


def evaluate_pending(alpaca_client, now: datetime) -> None:
    """Evaluate dispatched-alert outcomes (return signed by alert direction)."""
    _evaluate_log(alpaca_client, now, ALERTS_LOG, "price_at_alert",
                  lambda e: e.get("direction", 1))


def evaluate_pending_recommendations(alpaca_client, now: datetime) -> None:
    """Evaluate recommendation outcomes (long pick → +return is a hit; short
    pick → −return is a hit)."""
    _evaluate_log(alpaca_client, now, RECS_LOG, "price_at_pick",
                  lambda e: 1 if e.get("direction") == "long" else -1)


def compile_stats(now: datetime) -> dict:
    """Roll up the last 30 days into per-type hit-rate + avg-return stats."""
    entries = _read_entries()
    cutoff = (now - timedelta(days=30)).isoformat()
    recent = [e for e in entries if e["ts"] >= cutoff]

    per_type: dict[str, dict] = {}
    for e in recent:
        t = e["type"]
        # Normalize macro:* → macro for aggregation
        key = t.split(":")[0] if ":" in t else t
        per_type.setdefault(key, {"count": 0, "horizons": {h: {"n": 0, "hits": 0, "returns": []} for h in HORIZONS}})
        per_type[key]["count"] += 1
        for h in HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            per_type[key]["horizons"][h]["n"] += 1
            if ev["signed_return_pct"] > 0:
                per_type[key]["horizons"][h]["hits"] += 1
            per_type[key]["horizons"][h]["returns"].append(ev["signed_return_pct"])

    out: dict = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "total_alerts": len(recent),
        "per_type": {},
    }
    for atype, stats in per_type.items():
        horizons = {}
        for h, hs in stats["horizons"].items():
            n = hs["n"]
            horizons[f"{h}d"] = {
                "evaluated": n,
                "hit_rate": round(hs["hits"] / n, 3) if n else None,
                "avg_return_pct": round(sum(hs["returns"]) / n, 2) if n else None,
            }
        out["per_type"][atype] = {"count": stats["count"], "horizons": horizons}

    PERFORMANCE_FILE.write_text(json.dumps(out, indent=2))
    log.info(
        "Performance stats: %d alerts in 30d, %d types",
        out["total_alerts"], len(out["per_type"]),
    )
    return out


def log_recommendations(recommendations: dict, rows: list[dict], now: datetime,
                         regime: dict | None = None) -> None:
    """Append this scan's recommendation picks to the log with their entry
    price, so 1/3/5-day outcomes can be evaluated on later scans.

    Also persists a feature vector (rsi/macd/vol/news/etc) and the regime
    snapshot per pick — these let future analyses regress forward return
    against feature×regime instead of just score band.
    """
    by_ticker = {r["ticker"]: r for r in rows}
    new_entries = []
    for direction in ("longs", "shorts"):
        for rec in recommendations.get(direction, []):
            t = rec.get("ticker")
            row = by_ticker.get(t)
            if not row or row.get("price") is None:
                continue
            entry = {
                "ts": now.astimezone(timezone.utc).isoformat(),
                "ticker": t,
                "direction": rec.get("direction", "long"),
                "score": rec.get("score", 0),
                "price_at_pick": row["price"],
                "evaluations": {},
                "features": _extract_features(row),
            }
            if regime:
                entry["regime"] = regime
            # Capture the desk verdict (compact) so we can later measure whether
            # the agents' take/pass calls actually separate winners from losers.
            d = rec.get("desk")
            if d:
                entry["desk"] = {
                    "decision": d.get("decision"),
                    "size": d.get("size"),
                    "agreement": d.get("agreement"),
                    "signal_vote": (d.get("signal") or {}).get("vote"),
                    "research_vote": (d.get("research") or {}).get("vote"),
                    "risk_veto": (d.get("risk") or {}).get("veto"),
                }
            new_entries.append(entry)
    if new_entries:
        with open(RECS_LOG, "a") as f:
            for e in new_entries:
                f.write(json.dumps(e) + "\n")
        log.info("Logged %d recommendations for performance tracking", len(new_entries))


def compile_recommendation_stats(now: datetime) -> dict:
    """Roll up the last 30 days of recommendation picks into hit-rate +
    avg-return stats, split by direction and score band (lo: <HIGH_SCORE,
    hi: >=HIGH_SCORE) so the score's predictive value is visible."""
    entries = _read_entries(RECS_LOG)
    cutoff = (now - timedelta(days=30)).isoformat()
    recent = [e for e in entries if e["ts"] >= cutoff]

    buckets: dict[str, dict] = {}
    for e in recent:
        direction = e.get("direction", "long")
        band = "hi" if e.get("score", 0) >= HIGH_SCORE else "lo"
        key = f"{direction}_{band}"
        bucket = buckets.setdefault(
            key,
            {"count": 0, "horizons": {h: {"n": 0, "hits": 0, "returns": []} for h in HORIZONS}},
        )
        bucket["count"] += 1
        for h in HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            bucket["horizons"][h]["n"] += 1
            if ev["signed_return_pct"] > 0:
                bucket["horizons"][h]["hits"] += 1
            bucket["horizons"][h]["returns"].append(ev["signed_return_pct"])

    out: dict = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "total_picks": len(recent),
        "high_score": HIGH_SCORE,
        "per_bucket": {},
    }
    for key, stats in buckets.items():
        horizons = {}
        for h, hs in stats["horizons"].items():
            n = hs["n"]
            horizons[f"{h}d"] = {
                "evaluated": n,
                "hit_rate": round(hs["hits"] / n, 3) if n else None,
                "avg_return_pct": round(sum(hs["returns"]) / n, 2) if n else None,
            }
        out["per_bucket"][key] = {"count": stats["count"], "horizons": horizons}

    RECOMMENDATION_PERFORMANCE_FILE.write_text(json.dumps(out, indent=2))
    log.info(
        "Recommendation stats: %d picks in 30d, %d buckets",
        out["total_picks"], len(out["per_bucket"]),
    )
    return out


def compile_desk_stats(now: datetime) -> dict:
    """Roll up the agent desk's calls vs forward returns, reusing the 1/3/5-day
    evaluations already on the recommendations log (no extra Alpaca calls).

    The headline question: of all the picks recommend.py generated, do the ones
    the desk said 'take' actually outperform the ones it said 'pass'? If
    take_avg > pass_avg, the four agents are adding value — separating winners
    from losers. We also split by agreement level and the Risk veto to see which
    signal is carrying the edge.
    """
    entries = _read_entries(RECS_LOG)
    cutoff = (now - timedelta(days=30)).isoformat()
    recent = [e for e in entries if e["ts"] >= cutoff and e.get("desk")]

    def _new() -> dict:
        return {"count": 0, "horizons": {h: {"n": 0, "hits": 0, "returns": []} for h in HORIZONS}}

    def _add(bucketmap: dict, key: str, e: dict) -> None:
        b = bucketmap.setdefault(key, _new())
        b["count"] += 1
        for h in HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            b["horizons"][h]["n"] += 1
            if ev["signed_return_pct"] > 0:
                b["horizons"][h]["hits"] += 1
            b["horizons"][h]["returns"].append(ev["signed_return_pct"])

    by_decision: dict[str, dict] = {}
    by_agreement: dict[str, dict] = {}
    by_veto: dict[str, dict] = {}
    for e in recent:
        d = e["desk"]
        _add(by_decision, d.get("decision") or "unknown", e)
        _add(by_agreement, d.get("agreement") or "unknown", e)
        _add(by_veto, "veto" if d.get("risk_veto") else "no_veto", e)

    def _finalize(bucketmap: dict) -> dict:
        out: dict = {}
        for key, stats in bucketmap.items():
            horizons = {}
            for h, hs in stats["horizons"].items():
                n = hs["n"]
                horizons[f"{h}d"] = {
                    "evaluated": n,
                    "hit_rate": round(hs["hits"] / n, 3) if n else None,
                    "avg_return_pct": round(sum(hs["returns"]) / n, 2) if n else None,
                }
            out[key] = {"count": stats["count"], "horizons": horizons}
        return out

    decision_stats = _finalize(by_decision)

    # The desk's edge: take avg − pass avg per horizon. Positive => the agents
    # are correctly separating winners from losers (the whole point).
    edge: dict[str, float | None] = {}
    for h in HORIZONS:
        take = decision_stats.get("take", {}).get("horizons", {}).get(f"{h}d", {}).get("avg_return_pct")
        passed = decision_stats.get("pass", {}).get("horizons", {}).get(f"{h}d", {}).get("avg_return_pct")
        edge[f"{h}d"] = round(take - passed, 2) if (take is not None and passed is not None) else None

    out = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "total_with_desk": len(recent),
        "by_decision": decision_stats,
        "by_agreement": _finalize(by_agreement),
        "by_veto": _finalize(by_veto),
        "take_minus_pass_edge": edge,
    }
    DESK_PERFORMANCE_FILE.write_text(json.dumps(out, indent=2))
    log.info("Desk stats: %d picks with verdicts in 30d; take−pass edge %s", len(recent), edge)
    return out
