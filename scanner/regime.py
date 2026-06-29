"""Market regime detection.

Fetches SPY (and optionally QQQ / VXX) daily bars on each scan and computes
trend / vol-regime indicators. The output gets:
  1. passed to recommend.compute() to gate short picks in bull regimes
  2. persisted on every logged pick + alert via performance.log_* so future
     analysis can stratify hit rates by regime.

Self-contained Alpaca fetch (250 calendar days → ~170 trading days, enough
for a 200-day MA). Fails soft: returns {} on any error so callers can no-op
gracefully — no scan ever crashes because regime data is unavailable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from scanner import technicals

log = logging.getLogger(__name__)

# Tickers we always pull for regime context. SPY = US equity tape; QQQ = tech
# beta; VXX = VIX proxy (Alpaca doesn't carry the ^VIX index itself).
REGIME_SYMBOLS = ["SPY", "QQQ", "VXX"]

# Bars window — needs to cover the 200-day MA. 280 calendar days → ~195
# trading days, with cushion for holidays / dropped bars.
_HISTORY_DAYS = 280


def _fetch_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """One-shot Alpaca fetch for the regime symbols. Reuses the technicals
    client but with a longer history window than the main scan."""
    client = getattr(technicals, "_CLIENT", None)
    if client is None:
        return {}
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed, Adjustment
    except ImportError:
        return {}

    end_dt = datetime.now(timezone.utc) - timedelta(minutes=20)
    start_dt = end_dt - timedelta(days=_HISTORY_DAYS)
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start_dt,
            end=end_dt,
            feed=DataFeed.IEX,
            adjustment=Adjustment.ALL,
        )
        bars = client.get_stock_bars(req)
    except Exception as e:
        log.warning("Regime bars fetch failed: %s", e)
        return {}

    if bars.df is None or bars.df.empty:
        return {}

    out: dict[str, pd.DataFrame] = {}
    df = bars.df
    if "symbol" in df.index.names:
        for symbol in df.index.get_level_values("symbol").unique():
            sub = df.xs(symbol, level="symbol").copy()
            sub = sub.rename(
                columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
            )
            out[symbol] = sub
    return out


def _trend_metrics(closes: pd.Series, current: float) -> dict:
    """Compute the trend flags we care about for one symbol."""
    if closes.empty:
        return {}
    metrics: dict = {}
    n = len(closes)
    if n >= 2:
        prev = float(closes.iloc[-2])
        metrics["pct_1d"] = round((current / prev - 1) * 100, 2) if prev else None
    if n >= 6:
        prev5 = float(closes.iloc[-6])
        metrics["pct_5d"] = round((current / prev5 - 1) * 100, 2) if prev5 else None
    if n >= 50:
        ma50 = float(closes.tail(50).mean())
        metrics["ma_50"] = round(ma50, 2)
        metrics["above_50d"] = current > ma50
    if n >= 200:
        ma200 = float(closes.tail(200).mean())
        metrics["ma_200"] = round(ma200, 2)
        metrics["above_200d"] = current > ma200
    return metrics


def compute() -> dict:
    """Compute the current market regime snapshot.

    Returns {} if Alpaca is unavailable — callers must handle the empty case
    (recommend.compute, performance.log_* both treat empty regime as "unknown",
    skipping the bull-regime short suppression and leaving the regime field
    null on logged entries).
    """
    bars = _fetch_bars(REGIME_SYMBOLS)
    if not bars:
        log.warning("Regime: no bars available, returning empty regime dict")
        return {}

    out: dict = {"as_of": datetime.now(timezone.utc).isoformat()}

    spy = bars.get("SPY")
    if spy is not None and not spy.empty:
        closes = spy["Close"].astype(float)
        spy_price = float(closes.iloc[-1])
        spy_metrics = _trend_metrics(closes, spy_price)
        out["spy_price"] = round(spy_price, 2)
        out.update({f"spy_{k}": v for k, v in spy_metrics.items()})

    qqq = bars.get("QQQ")
    if qqq is not None and not qqq.empty:
        closes = qqq["Close"].astype(float)
        qqq_price = float(closes.iloc[-1])
        qqq_metrics = _trend_metrics(closes, qqq_price)
        out["qqq_price"] = round(qqq_price, 2)
        out.update({f"qqq_{k}": v for k, v in qqq_metrics.items()})

    vxx = bars.get("VXX")
    if vxx is not None and not vxx.empty:
        closes = vxx["Close"].astype(float)
        vxx_price = float(closes.iloc[-1])
        out["vxx_price"] = round(vxx_price, 2)
        # 20-day average as the "normal" baseline; current/avg > 1.3 = stressed.
        if len(closes) >= 20:
            avg20 = float(closes.tail(20).mean())
            out["vxx_avg_20d"] = round(avg20, 2)
            out["vxx_stress_ratio"] = round(vxx_price / avg20, 2) if avg20 else None

    # Derived regime label — a single string that's easier to filter on than
    # juggling the booleans. "risk_on" = SPY above 50d AND VXX not stressed;
    # "risk_off" = either SPY below 200d OR VXX stress ratio > 1.4; "mixed"
    # otherwise (the choppy regime where shorts whipsaw and longs underperform).
    spy_above_50d = out.get("spy_above_50d")
    spy_above_200d = out.get("spy_above_200d")
    vxx_stress = out.get("vxx_stress_ratio")
    if spy_above_50d is True and (vxx_stress is None or vxx_stress < 1.3):
        out["label"] = "risk_on"
    elif spy_above_200d is False or (vxx_stress is not None and vxx_stress > 1.4):
        out["label"] = "risk_off"
    else:
        out["label"] = "mixed"

    log.info(
        "Regime: %s (SPY %s vs 50d, %s vs 200d; VXX stress %s)",
        out.get("label"),
        spy_above_50d, spy_above_200d, vxx_stress,
    )
    return out
