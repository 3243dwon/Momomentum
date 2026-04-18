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

RETENTION_DAYS = 45
HORIZONS = [1, 3, 5]  # days


def _read_entries() -> list[dict]:
    if not ALERTS_LOG.exists():
        return []
    entries = []
    for line in ALERTS_LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def _write_entries(entries: list[dict]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    entries = [e for e in entries if e["ts"] >= cutoff]
    with open(ALERTS_LOG, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def log_alerts(alerts: list[dict], rows: list[dict], now: datetime) -> None:
    """Append dispatched alerts to the log. Macro alerts (no ticker) are skipped."""
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
        new_entries.append(entry)
    if new_entries:
        with open(ALERTS_LOG, "a") as f:
            for e in new_entries:
                f.write(json.dumps(e) + "\n")
        log.info("Logged %d alerts for performance tracking", len(new_entries))


def evaluate_pending(alpaca_client, now: datetime) -> None:
    """For each log entry past a horizon without an eval, fetch current price."""
    if alpaca_client is None:
        return
    entries = _read_entries()
    pending: list[tuple[int, str, int]] = []
    for i, entry in enumerate(entries):
        try:
            alert_time = datetime.fromisoformat(entry["ts"])
        except Exception:
            continue
        if alert_time.tzinfo is None:
            alert_time = alert_time.replace(tzinfo=timezone.utc)
        age_days = (now - alert_time).total_seconds() / 86400
        for h in HORIZONS:
            key = f"{h}d"
            if key in entry.get("evaluations", {}):
                continue
            if age_days < h:
                continue
            pending.append((i, entry["ticker"], h))

    if not pending:
        return

    # Batch unique tickers for a single Alpaca snapshot call
    unique_tickers = sorted({t for _, t, _ in pending})
    try:
        from alpaca.data.requests import StockSnapshotRequest
        from alpaca.data.enums import DataFeed
        req = StockSnapshotRequest(symbol_or_symbols=unique_tickers, feed=DataFeed.IEX)
        snaps = alpaca_client.get_stock_snapshot(req)
    except Exception as e:
        log.warning("Performance evaluation Alpaca fetch failed: %s", e)
        return

    current_prices: dict[str, float] = {}
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
                    current_prices[symbol] = float(p)
                    break
        except Exception:
            pass

    updated = 0
    for idx, ticker, h in pending:
        if ticker not in current_prices:
            continue
        entry = entries[idx]
        entry_price = entry.get("price_at_alert")
        if not entry_price:
            continue
        current = current_prices[ticker]
        return_pct = (current / entry_price - 1) * 100
        signed = return_pct * entry.get("direction", 1)
        entry.setdefault("evaluations", {})[f"{h}d"] = {
            "price": round(current, 2),
            "return_pct": round(return_pct, 2),
            "signed_return_pct": round(signed, 2),
        }
        updated += 1

    if updated:
        _write_entries(entries)
        log.info("Evaluated %d pending alert horizons", updated)


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
