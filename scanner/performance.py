"""Alert performance tracking.

Every dispatched alert is logged with the alert-time price + direction.
On each scan, entries past their evaluation horizon (1d / 3d / 5d) get a
current-price lookup via Alpaca and a signed-return computed in the direction
of the original alert.

Stats are compiled over a 30-day trailing window and written to
data/performance.json for the web app.
"""
from __future__ import annotations

import hashlib
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
PREDICTIONS_LOG = config.CACHE_DIR / "predictions_log.jsonl"
PREDICTION_PERFORMANCE_FILE = config.DATA_DIR / "prediction_performance.json"
LEDGER_FILE = config.DATA_DIR / "ledger.json"            # committed; permanent public record
# Early-entry (scanner.opening) catch-list tier. Log lives in the evictable
# cache like the others; stats + the ledger entries below are committed.
EARLY_ENTRY_LOG = config.CACHE_DIR / "early_entry_log.jsonl"
EARLY_ENTRY_PERFORMANCE_FILE = config.DATA_DIR / "early_entry_performance.json"

RETENTION_DAYS = 45
HORIZONS = [1, 3, 5, 10, 21]  # days — 10d/21d capture catalyst drift (max graded hold)
# Early-entry is an intraday-momentum call: 0d = return to the entry-day close
# is the primary grade; 1d/3d measure follow-through.
EARLY_HORIZONS = [0, 1, 3]  # trading days
SPY_SYMBOL = "SPY"  # benchmark leg for excess-vs-market on recommendation picks
HIGH_SCORE = 7  # recommendation score >= this is bucketed as a high-conviction pick
# Flat round-trip slippage drag applied to net stats (docs/perf-roadmap.md:
# 0.3-0.8% is realistic for the mid/small caps the scanner surfaces).
SLIPPAGE_PCT = 0.5
# A persistent pick re-surfacing within this window is the SAME call, not a
# new one — re-logging it every 2-3h scan inflated n ~5x.
REC_DEDUP_HOURS = 20


def _parse_ts(ts: str) -> datetime | None:
    """ISO string → aware UTC datetime. None when unparseable."""
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def _segment(ticker: str, popular_set: set[str]) -> str:
    """Universe segment for a pick: "large" if the ticker is in the popular
    (S&P 500 ∪ NDX) set, else "tail". On an unbuilt universe.json popular_set
    is empty, so every pick tags "tail" (graceful degrade)."""
    return "large" if ticker in popular_set else "tail"


def _alert_direction(alert: dict, pct: float) -> tuple[int, str]:
    """(direction, basis) for one alert.

    Alert types that carry an actual stance — ripple (bullish/bearish) and
    serenity_match (tweet stance) — are graded on the THESIS direction.
    Pure momentum types (big_move, watchlist, delta_*, catalyst) have no
    stance; their sign-of-move "direction" measures continuation, and the
    basis tag lets the UI label those stats honestly.
    """
    atype = alert.get("type", "")
    if atype == "ripple":
        d = alert.get("direction")
        if d in ("bullish", "bearish"):
            return (1 if d == "bullish" else -1), "thesis"
    elif atype == "serenity_match":
        s = alert.get("stance")
        if s in ("bull", "bullish"):
            return 1, "thesis"
        if s in ("bear", "bearish"):
            return -1, "thesis"
    return (1 if pct >= 0 else -1), "move"


def log_alerts(alerts: list[dict], rows: list[dict], now: datetime,
                regime: dict | None = None) -> None:
    """Append dispatched alerts to the log. Macro alerts (no ticker) are skipped.

    `regime` (optional) is the output of scanner.regime.compute() — stored on
    each entry so future analysis can split hit rates by regime label.
    """
    by_ticker = {r["ticker"]: r for r in rows}
    new_entries = []
    for alert in alerts:
        t = alert.get("ticker")
        if not t:
            continue
        row = by_ticker.get(t)
        if not row or row.get("price") is None:
            continue
        pct = row.get("pct_1d") or 0
        direction, basis = _alert_direction(alert, pct)
        entry = {
            "ts": now.astimezone(timezone.utc).isoformat(),
            "ticker": t,
            "type": alert.get("type", "unknown"),
            "title": alert.get("title", ""),
            "price_at_alert": row["price"],
            "pct_1d_at_alert": pct,
            "direction": direction,
            "direction_basis": basis,
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
                  price_key: str, sign_fn, bench_key: str | None = None) -> None:
    """For each entry in log_path past a horizon without an eval, fetch the
    current price and record a return signed by sign_fn(entry) (+1 / -1).

    When `bench_key` is set (the entry field holding the pick-time SPY price,
    e.g. "spy_price_at_pick"), SPY is added to the SAME live snapshot batch so
    excess-vs-SPY is computed point-in-time off the identical end snapshot as
    the stock leg — no separate / as-of SPY bar, no look-ahead. Callers that
    pass no bench_key (alerts / predictions) behave byte-identically."""
    if alpaca_client is None:
        return
    entries = _read_entries(log_path)
    pending: list[tuple[int, str, int]] = []
    for i, entry in enumerate(entries):
        if entry.get(price_key) is None:
            continue  # untracked (no entry price) — excluded from evaluation
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

    # SPY rides in the same batch as the real picks — one shared snapshot. It is
    # never iterated as a pick (the loop walks `pending`, built from real
    # tickers only); it's read solely via prices.get(SPY_SYMBOL).
    fetch_tickers = {t for _, t, _ in pending}
    if bench_key:
        fetch_tickers.add(SPY_SYMBOL)
    prices = _fetch_current_prices(alpaca_client, sorted(fetch_tickers))
    if not prices:
        return
    spy_now = prices.get(SPY_SYMBOL) if bench_key else None

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
        ev: dict = {
            "price": round(current, 2),
            "return_pct": round(return_pct, 2),
            "signed_return_pct": round(signed, 2),
        }
        # Excess-vs-SPY: same start anchor (spy_price_at_pick) + same end
        # snapshot (spy_now) as the stock leg. Computed from unrounded legs,
        # rounded once. Skipped silently for legacy rows without spy_price_at_pick.
        if bench_key:
            spy_at_pick = entry.get(bench_key)
            if spy_at_pick and spy_now:
                spy_return_pct = (spy_now / spy_at_pick - 1) * 100
                ev["spy_return_pct"] = round(spy_return_pct, 2)
                ev["excess_return_pct"] = round(signed - spy_return_pct, 2)
        entry.setdefault("evaluations", {})[f"{h}d"] = ev
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
    pick → −return is a hit). bench_key adds the SPY excess leg (recs only)."""
    _evaluate_log(alpaca_client, now, RECS_LOG, "price_at_pick",
                  lambda e: 1 if e.get("direction") == "long" else -1,
                  bench_key="spy_price_at_pick")


def evaluate_pending_predictions(alpaca_client, now: datetime) -> None:
    """Evaluate ripple-prediction outcomes (bullish call → +return is a hit;
    bearish call → −return is a hit), reusing the generic horizon evaluator."""
    _evaluate_log(alpaca_client, now, PREDICTIONS_LOG, "price_at_prediction",
                  lambda e: 1 if e.get("direction") == "bullish" else -1)


def _horizon_stats(returns: list[float], excess: list | None = None) -> dict:
    """Gross AND net-of-slippage stats for one horizon bucket. Net applies the
    flat SLIPPAGE_PCT round-trip drag to every signed return.

    When `excess` is supplied (same length as `returns`; None entries allowed
    for legacy rows that predate spy_price_at_pick), the bucket also carries
    avg_excess_pct (mean of non-None excess) + hit_rate_excess (share of
    non-None excess > 0). excess=None keeps the original shape byte-for-byte."""
    n = len(returns)
    if not n:
        out = {
            "evaluated": 0,
            "hit_rate": None, "avg_return_pct": None,
            "hit_rate_net": None, "avg_return_net_pct": None,
        }
        if excess is not None:
            out["avg_excess_pct"] = None
            out["hit_rate_excess"] = None
        return out
    net = [r - SLIPPAGE_PCT for r in returns]
    out = {
        "evaluated": n,
        "hit_rate": round(sum(1 for r in returns if r > 0) / n, 3),
        "avg_return_pct": round(sum(returns) / n, 2),
        "hit_rate_net": round(sum(1 for r in net if r > 0) / n, 3),
        "avg_return_net_pct": round(sum(net) / n, 2),
    }
    if excess is not None:
        vals = [x for x in excess if x is not None]
        m = len(vals)
        out["avg_excess_pct"] = round(sum(vals) / m, 2) if m else None
        out["hit_rate_excess"] = round(sum(1 for x in vals if x > 0) / m, 3) if m else None
    return out


def compile_stats(now: datetime) -> dict:
    """Roll up the last 30 days into per-type hit-rate + avg-return stats
    (gross and net of slippage), tagged with each type's dominant
    direction_basis so the UI can label move-based stats as continuation
    rather than thesis accuracy."""
    entries = _read_entries()
    cutoff = (now - timedelta(days=30)).isoformat()
    recent = [e for e in entries if e["ts"] >= cutoff]

    per_type: dict[str, dict] = {}
    for e in recent:
        t = e["type"]
        # Normalize macro:* → macro for aggregation
        key = t.split(":")[0] if ":" in t else t
        per_type.setdefault(key, {"count": 0, "basis": {}, "horizons": {h: [] for h in HORIZONS}})
        per_type[key]["count"] += 1
        basis = e.get("direction_basis") or "move"  # legacy entries were sign-of-move
        per_type[key]["basis"][basis] = per_type[key]["basis"].get(basis, 0) + 1
        for h in HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            per_type[key]["horizons"][h].append(ev["signed_return_pct"])

    out: dict = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "slippage_round_trip_pct": SLIPPAGE_PCT,
        "total_alerts": len(recent),
        "per_type": {},
    }
    for atype, stats in per_type.items():
        horizons = {f"{h}d": _horizon_stats(rets) for h, rets in stats["horizons"].items()}
        dominant_basis = max(stats["basis"], key=stats["basis"].get) if stats["basis"] else "move"
        out["per_type"][atype] = {
            "count": stats["count"],
            "direction_basis": dominant_basis,
            "horizons": horizons,
        }

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

    Cross-scan dedup: a (ticker, direction) already logged within the last
    REC_DEDUP_HOURS is the same persistent pick re-surfacing on the next
    2-3h scan, not a new call — re-logging it inflated n ~5x.
    """
    by_ticker = {r["ticker"]: r for r in rows}

    # SPY pick-time price (excess-vs-market start anchor) + the popular set for
    # universe_segment, both resolved ONCE per call. popular() fails soft to an
    # empty set on an unbuilt universe.json -> every pick tags "tail".
    spy_at_pick = (regime or {}).get("spy_price")
    try:
        from scanner import universe as _universe
        popular_set = _universe.popular()
    except Exception:
        popular_set = set()

    dedup_cutoff = now.astimezone(timezone.utc) - timedelta(hours=REC_DEDUP_HOURS)
    recently_logged: set[tuple[str, str]] = set()
    for e in _read_entries(RECS_LOG):
        ts = _parse_ts(e.get("ts", ""))
        if ts is not None and ts >= dedup_cutoff:
            recently_logged.add((e.get("ticker"), e.get("direction", "long")))

    new_entries = []
    skipped_dupes = 0
    for direction in ("longs", "shorts"):
        for rec in recommendations.get(direction, []):
            t = rec.get("ticker")
            row = by_ticker.get(t)
            if not row or row.get("price") is None:
                continue
            if (t, rec.get("direction", "long")) in recently_logged:
                skipped_dupes += 1
                continue
            entry = {
                "ts": now.astimezone(timezone.utc).isoformat(),
                "ticker": t,
                "direction": rec.get("direction", "long"),
                "score": rec.get("score", 0),
                "thesis": "; ".join((rec.get("reasons") or [])[:3]),
                "price_at_pick": row["price"],
                "spy_price_at_pick": spy_at_pick,
                "universe_segment": _segment(t, popular_set),
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
    if new_entries or skipped_dupes:
        with open(RECS_LOG, "a") as f:
            for e in new_entries:
                f.write(json.dumps(e) + "\n")
        log.info(
            "Logged %d unique recommendations for performance tracking "
            "(%d suppressed as repeats within %dh)",
            len(new_entries), skipped_dupes, REC_DEDUP_HOURS,
        )


def compile_recommendation_stats(now: datetime) -> dict:
    """Roll up the last 30 days of recommendation picks into hit-rate +
    avg-return stats, split by direction and score band (lo: <HIGH_SCORE,
    hi: >=HIGH_SCORE) so the score's predictive value is visible."""
    entries = _read_entries(RECS_LOG)
    cutoff = (now - timedelta(days=30)).isoformat()
    recent = [e for e in entries if e["ts"] >= cutoff]

    def _new() -> dict:
        return {"count": 0, "horizons": {h: {"returns": [], "excess": []} for h in HORIZONS}}

    def _add(bucketmap: dict, key: str, e: dict) -> None:
        b = bucketmap.setdefault(key, _new())
        b["count"] += 1
        for h in HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            b["horizons"][h]["returns"].append(ev["signed_return_pct"])
            # Excess is None for legacy rows / horizons missing the SPY leg;
            # _horizon_stats skips the Nones when averaging.
            b["horizons"][h]["excess"].append(ev.get("excess_return_pct"))

    def _finalize(bucketmap: dict) -> dict:
        return {
            key: {
                "count": stats["count"],
                "horizons": {
                    f"{h}d": _horizon_stats(hs["returns"], hs["excess"])
                    for h, hs in stats["horizons"].items()
                },
            }
            for key, stats in bucketmap.items()
        }

    # Same direction×band bucketing, plus a NEW per_segment view keyed by
    # universe_segment (large/tail). per_bucket keeps its shape (now with the
    # previously-missing net fields + excess), per_segment is additive.
    by_bucket: dict[str, dict] = {}
    by_segment: dict[str, dict] = {}
    for e in recent:
        direction = e.get("direction", "long")
        band = "hi" if e.get("score", 0) >= HIGH_SCORE else "lo"
        _add(by_bucket, f"{direction}_{band}", e)
        _add(by_segment, f"{direction}_{e.get('universe_segment', 'tail')}", e)

    out: dict = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "slippage_round_trip_pct": SLIPPAGE_PCT,
        "total_picks": len(recent),
        "high_score": HIGH_SCORE,
        "per_bucket": _finalize(by_bucket),
        "per_segment": _finalize(by_segment),
    }

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
        return {"count": 0, "horizons": {h: {"returns": [], "excess": []} for h in HORIZONS}}

    def _add(bucketmap: dict, key: str, e: dict) -> None:
        b = bucketmap.setdefault(key, _new())
        b["count"] += 1
        for h in HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            b["horizons"][h]["returns"].append(ev["signed_return_pct"])
            b["horizons"][h]["excess"].append(ev.get("excess_return_pct"))

    by_decision: dict[str, dict] = {}
    by_agreement: dict[str, dict] = {}
    by_veto: dict[str, dict] = {}
    for e in recent:
        d = e["desk"]
        _add(by_decision, d.get("decision") or "unknown", e)
        _add(by_agreement, d.get("agreement") or "unknown", e)
        _add(by_veto, "veto" if d.get("risk_veto") else "no_veto", e)

    def _finalize(bucketmap: dict) -> dict:
        return {
            key: {
                "count": stats["count"],
                "horizons": {
                    f"{h}d": _horizon_stats(hs["returns"], hs["excess"])
                    for h, hs in stats["horizons"].items()
                },
            }
            for key, stats in bucketmap.items()
        }

    decision_stats = _finalize(by_decision)

    # The desk's edge: take avg − pass avg per horizon. Positive => the agents
    # are correctly separating winners from losers (the whole point). Mirrored
    # on net (post-slippage) and excess (vs SPY); excess edge is null until
    # spy_price_at_pick was logged AND SPY fetched — expected early sparsity.
    def _edge(field: str) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for h in HORIZONS:
            take = decision_stats.get("take", {}).get("horizons", {}).get(f"{h}d", {}).get(field)
            passed = decision_stats.get("pass", {}).get("horizons", {}).get(f"{h}d", {}).get(field)
            out[f"{h}d"] = round(take - passed, 2) if (take is not None and passed is not None) else None
        return out

    out = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "total_with_desk": len(recent),
        "by_decision": decision_stats,
        "by_agreement": _finalize(by_agreement),
        "by_veto": _finalize(by_veto),
        "take_minus_pass_edge": _edge("avg_return_pct"),
        "take_minus_pass_edge_net": _edge("avg_return_net_pct"),
        "take_minus_pass_edge_excess": _edge("avg_excess_pct"),
    }
    DESK_PERFORMANCE_FILE.write_text(json.dumps(out, indent=2))
    log.info("Desk stats: %d picks with verdicts in 30d; take−pass edge %s",
             len(recent), out["take_minus_pass_edge"])
    return out


def log_predictions(predictions: list[dict], rows: list[dict], now: datetime,
                    regime: dict | None = None) -> None:
    """Append this scan's ripple predictions to the log with their entry price,
    so 1/3/5-day outcomes can be evaluated later.

    Predicted names with no scan-row price — exactly the not-in-scan names the
    ripple tier pushes hardest — are NOT dropped: we best-effort fetch an entry
    price via the same Alpaca snapshot util the evaluator uses; if that fails
    they're logged with price_at_prediction=null and status "untracked"
    (excluded from evaluation, surfaced as untracked_count in the stats).

    `priced_in` and `confidence` are stored so compile_prediction_stats can
    isolate the honest headline: how do the NOT-yet-priced-in calls actually do?
    """
    by_ticker = {r["ticker"]: r for r in rows}

    # Best-effort entry prices for names without a scan-row price.
    missing = sorted({
        p["ticker"] for p in predictions
        if p.get("ticker") and (by_ticker.get(p["ticker"]) or {}).get("price") is None
    })
    fetched: dict[str, float] = {}
    if missing:
        try:
            from scanner import technicals as _technicals
            alpaca = getattr(_technicals, "_CLIENT", None)
            if alpaca is not None:
                fetched = _fetch_current_prices(alpaca, missing)
        except Exception as e:
            log.warning("Prediction entry-price fetch failed: %s", e)

    new_entries = []
    untracked = 0
    for p in predictions:
        t = p.get("ticker")
        if not t:
            continue
        row = by_ticker.get(t)
        price = row.get("price") if row else None
        if price is None:
            price = fetched.get(t)
        entry = {
            "ts": now.astimezone(timezone.utc).isoformat(),
            "ticker": t,
            "type": "ripple",
            "direction": p.get("direction", "bullish"),
            "confidence": p.get("confidence", "low"),
            "priced_in": p.get("priced_in", "no"),
            "horizon": p.get("horizon"),
            "trigger_ticker": p.get("trigger_ticker"),
            "thesis": (p.get("rationale") or "")[:200],
            "price_at_prediction": price,
            "evaluations": {},
        }
        if price is None:
            entry["status"] = "untracked"
            untracked += 1
        if regime:
            entry["regime"] = regime
        new_entries.append(entry)
    if new_entries:
        with open(PREDICTIONS_LOG, "a") as f:
            for e in new_entries:
                f.write(json.dumps(e) + "\n")
        log.info(
            "Logged %d predictions for performance tracking (%d untracked, no price)",
            len(new_entries), untracked,
        )


def compile_prediction_stats(now: datetime) -> dict:
    """Roll up the last 30 days of ripple predictions into hit-rate + avg-return
    (gross and net of slippage), split three ways: by confidence (does the
    model's confidence mean anything?), by priced_in (do the not-yet-moved
    'before' calls actually pay?) and by stated horizon — predictions claim up
    to weeks/months but everything is graded at the 1/3/5d HORIZONS, so the
    horizon split + horizon_note keep that honest."""
    entries = _read_entries(PREDICTIONS_LOG)
    cutoff = (now - timedelta(days=30)).isoformat()
    recent = [e for e in entries if e["ts"] >= cutoff]

    def _new() -> dict:
        return {"count": 0, "horizons": {h: [] for h in HORIZONS}}

    def _add(bucketmap: dict, key: str, e: dict) -> None:
        b = bucketmap.setdefault(key, _new())
        b["count"] += 1
        for h in HORIZONS:
            ev = e.get("evaluations", {}).get(f"{h}d")
            if not ev:
                continue
            b["horizons"][h].append(ev["signed_return_pct"])

    by_confidence: dict[str, dict] = {}
    by_priced_in: dict[str, dict] = {}
    by_horizon: dict[str, dict] = {}
    untracked_count = 0
    for e in recent:
        if e.get("status") == "untracked" or e.get("price_at_prediction") is None:
            untracked_count += 1
        _add(by_confidence, e.get("confidence", "low"), e)
        _add(by_priced_in, e.get("priced_in", "no"), e)
        _add(by_horizon, e.get("horizon") or "unspecified", e)

    def _finalize(bucketmap: dict) -> dict:
        return {
            key: {
                "count": stats["count"],
                "horizons": {f"{h}d": _horizon_stats(rets) for h, rets in stats["horizons"].items()},
            }
            for key, stats in bucketmap.items()
        }

    out = {
        "generated_at": now.isoformat(),
        "window_days": 30,
        "slippage_round_trip_pct": SLIPPAGE_PCT,
        "horizon_note": "calls graded at 1/3/5d regardless of stated horizon",
        "total_predictions": len(recent),
        "untracked_count": untracked_count,
        "by_confidence": _finalize(by_confidence),
        "by_priced_in": _finalize(by_priced_in),
        "by_horizon": _finalize(by_horizon),
    }
    PREDICTION_PERFORMANCE_FILE.write_text(json.dumps(out, indent=2))
    log.info(
        "Prediction stats: %d predictions in 30d (%d untracked)",
        len(recent), untracked_count,
    )
    return out


# --- Public accountability ledger --------------------------------------------
# The .jsonl logs live only in evictable Actions caches; data/ledger.json is
# the committed, permanent record of every call (alert / pick / prediction)
# with its entry price and graded outcomes.

LEDGER_WINDOW_DAYS = 30
LEDGER_MAX_ENTRIES = 500


def _ledger_id(kind: str, etype: str, ticker: str, ts: str) -> str:
    return hashlib.sha1(f"{kind}|{etype}|{ticker}|{ts}".encode("utf-8")).hexdigest()[:12]


def _ledger_entry(e: dict, kind: str, etype: str, direction: str | None,
                  confidence: str | None, price: float | None) -> dict:
    outcomes = {
        f"{h}d": (e.get("evaluations", {}).get(f"{h}d") or {}).get("signed_return_pct")
        for h in HORIZONS
    }
    if price is None:
        status = "untracked"
    elif outcomes["1d"] is not None:
        status = "hit" if outcomes["1d"] > 0 else "miss"
    else:
        status = "pending"
    ticker = e.get("ticker", "")
    ts = e.get("ts", "")
    return {
        "id": _ledger_id(kind, etype, ticker, ts),
        "ts": ts,
        "kind": kind,
        "type": etype,
        "ticker": ticker,
        "direction": direction,
        "confidence": confidence,
        "price": price,
        "thesis": e.get("thesis") or e.get("title") or "",
        "outcomes": outcomes,
        "status": status,
    }


def write_ledger(now: datetime) -> dict:
    """Write data/ledger.json — last LEDGER_WINDOW_DAYS of alerts, picks and
    predictions, newest first, capped at LEDGER_MAX_ENTRIES. Fail-soft: any
    error logs a warning and leaves the previous file in place."""
    try:
        cutoff = now.astimezone(timezone.utc) - timedelta(days=LEDGER_WINDOW_DAYS)
        entries: list[dict] = []

        for e in _read_entries(ALERTS_LOG):
            ts = _parse_ts(e.get("ts", ""))
            if ts is None or ts < cutoff or not e.get("ticker"):
                continue
            entries.append(_ledger_entry(
                e, "alert", e.get("type", "unknown"),
                "long" if e.get("direction", 1) >= 0 else "short",
                None, e.get("price_at_alert"),
            ))

        for e in _read_entries(RECS_LOG):
            ts = _parse_ts(e.get("ts", ""))
            if ts is None or ts < cutoff or not e.get("ticker"):
                continue
            direction = e.get("direction", "long")
            entries.append(_ledger_entry(
                e, "pick", f"rec_{direction}", direction,
                None, e.get("price_at_pick"),
            ))

        for e in _read_entries(PREDICTIONS_LOG):
            ts = _parse_ts(e.get("ts", ""))
            if ts is None or ts < cutoff or not e.get("ticker"):
                continue
            entries.append(_ledger_entry(
                e, "prediction", e.get("type", "ripple"),
                "long" if e.get("direction", "bullish") == "bullish" else "short",
                e.get("confidence"), e.get("price_at_prediction"),
            ))

        # Early-entry catch-list calls. Only FIRED candidates are calls (the
        # eligible-but-passed control cohort is measured in the stats, not the
        # public ledger). Graded at EARLY_HORIZONS; 0d (entry-day close) drives
        # the hit/miss status.
        for e in _read_entries(EARLY_ENTRY_LOG):
            ts = _parse_ts(e.get("ts", ""))
            if ts is None or ts < cutoff or not e.get("ticker") or not e.get("fired"):
                continue
            direction = e.get("direction", "long")
            price = e.get("price_at_entry")
            outcomes = {
                f"{h}d": (e.get("evaluations", {}).get(f"{h}d") or {}).get("signed_return_pct")
                for h in EARLY_HORIZONS
            }
            if price is None:
                status = "untracked"
            elif outcomes.get("0d") is not None:
                status = "hit" if outcomes["0d"] > 0 else "miss"
            else:
                status = "pending"
            entries.append({
                "id": _ledger_id("early_entry", f"catch_{direction}", e["ticker"], e.get("ts", "")),
                "ts": e.get("ts", ""),
                "kind": "early_entry",
                "type": f"catch_{direction}",
                "ticker": e["ticker"],
                "direction": direction,
                "confidence": None,
                "price": price,
                "thesis": e.get("thesis") or "",
                "outcomes": outcomes,
                "status": status,
            })

        entries.sort(key=lambda x: x["ts"], reverse=True)
        entries = entries[:LEDGER_MAX_ENTRIES]

        payload = {
            "generated_at": now.isoformat(),
            "window_days": LEDGER_WINDOW_DAYS,
            "entries": entries,
        }
        LEDGER_FILE.write_text(json.dumps(payload, indent=2))
        log.info("Wrote ledger.json: %d entries (%dd window)", len(entries), LEDGER_WINDOW_DAYS)
        return payload
    except Exception as e:
        log.warning("Ledger write failed: %s", e)
        return {}
