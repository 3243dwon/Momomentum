"""Alpaca Markets daily-bar fetcher + technical indicators.

Replaces yfinance — Yahoo's bot detection is hostile to scraping in 2026
and was returning empty data even from GitHub Actions runners. Alpaca
free paper-trading account gives 200 req/min on a real, official API.
Default IEX feed is sufficient for daily-bar momentum scanning.
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd

from scanner import config

log = logging.getLogger(__name__)

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY")
ALPACA_API_SECRET = os.environ.get("ALPACA_API_SECRET")

BATCH_SIZE = 100
HISTORY_DAYS = 90
RATE_LIMIT_DELAY = 0.35  # ~3 req/sec — well under Alpaca's 200/min free-tier cap

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed, Adjustment

    if ALPACA_API_KEY and ALPACA_API_SECRET:
        _CLIENT = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
        log.info("Alpaca data client initialized")
    else:
        _CLIENT = None
        log.warning("ALPACA_API_KEY / ALPACA_API_SECRET not set; technicals disabled")
except ImportError as _e:
    _CLIENT = None
    log.warning("alpaca-py not installed (%s); technicals disabled", _e)


def _rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return math.nan
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    if avg_loss.iloc[-1] == 0:
        return 100.0
    rs = avg_gain.iloc[-1] / avg_loss.iloc[-1]
    return float(100 - 100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[float, str | None]:
    if len(close) < 35:
        return math.nan, None
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    cross = None
    if len(hist) >= 2:
        if hist.iloc[-2] <= 0 < hist.iloc[-1]:
            cross = "bullish"
        elif hist.iloc[-2] >= 0 > hist.iloc[-1]:
            cross = "bearish"
    return float(hist.iloc[-1]), cross


def _compute_row(ticker: str, sub: pd.DataFrame) -> dict | None:
    sub = sub.dropna(how="all")
    if len(sub) < 30:
        return None
    close = sub["Close"].astype(float)
    volume = sub["Volume"].astype(float)

    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    pct_1d = (last_close / prev_close - 1) * 100 if prev_close else math.nan
    pct_5d = (
        (last_close / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else math.nan
    )

    last_volume = float(volume.iloc[-1])
    avg_volume_20d = float(volume.tail(21).iloc[:-1].mean()) if len(volume) >= 21 else math.nan
    rel_volume = (last_volume / avg_volume_20d) if avg_volume_20d else math.nan

    if last_close < config.MIN_PRICE:
        return None
    if not math.isnan(avg_volume_20d) and avg_volume_20d < config.MIN_AVG_VOLUME_20D:
        return None

    rsi = _rsi(close)
    macd_hist, macd_cross = _macd(close)

    flags = []
    if not math.isnan(rel_volume) and rel_volume >= config.REL_VOLUME_THRESHOLD:
        flags.append("unusual_volume")
    if not math.isnan(pct_1d) and abs(pct_1d) >= config.PCT_MOVE_THRESHOLD_RTH:
        flags.append("big_move")
    if macd_cross:
        flags.append(f"macd_{macd_cross}")
    if not math.isnan(rsi):
        if rsi >= 70:
            flags.append("overbought")
        elif rsi <= 30:
            flags.append("oversold")

    return {
        "ticker": ticker,
        "price": round(last_close, 2),
        "pct_1d": round(pct_1d, 2) if not math.isnan(pct_1d) else None,
        "pct_5d": round(pct_5d, 2) if not math.isnan(pct_5d) else None,
        "volume": int(last_volume) if not math.isnan(last_volume) else None,
        "avg_volume_20d": int(avg_volume_20d) if not math.isnan(avg_volume_20d) else None,
        "rel_volume": round(rel_volume, 2) if not math.isnan(rel_volume) else None,
        "rsi_14": round(rsi, 1) if not math.isnan(rsi) else None,
        "macd_hist": round(macd_hist, 3) if not math.isnan(macd_hist) else None,
        "macd_cross": macd_cross,
        "flags": flags,
    }


def _fetch_batch(symbols: list[str], start_dt: datetime, end_dt: datetime) -> dict[str, pd.DataFrame]:
    if not _CLIENT:
        return {}
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start_dt,
            end=end_dt,
            feed=DataFeed.IEX,
            adjustment=Adjustment.ALL,
        )
        bars = _CLIENT.get_stock_bars(req)
    except Exception as e:
        log.warning("Alpaca batch fetch failed (%d symbols): %s", len(symbols), e)
        return {}

    out: dict[str, pd.DataFrame] = {}
    if bars.df is None or bars.df.empty:
        return out

    df = bars.df
    if "symbol" in df.index.names:
        for symbol in df.index.get_level_values("symbol").unique():
            sub = df.xs(symbol, level="symbol").copy()
            sub = sub.rename(
                columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
            )
            out[symbol] = sub
    else:
        sub = df.rename(
            columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
        )
        out[symbols[0]] = sub
    return out


def scan(tickers: Iterable[str]) -> list[dict]:
    if not _CLIENT:
        log.error("No Alpaca client; returning empty scan. Check ALPACA_API_KEY / ALPACA_API_SECRET.")
        return []

    tickers = list(tickers)
    rows: list[dict] = []
    total = len(tickers)
    log.info("Scanning %d tickers via Alpaca in batches of %d", total, BATCH_SIZE)

    end_dt = datetime.now(timezone.utc) - timedelta(minutes=20)
    start_dt = end_dt - timedelta(days=HISTORY_DAYS)

    fetched_count = 0
    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        per_symbol = _fetch_batch(batch, start_dt, end_dt)
        fetched_count += len(per_symbol)
        for symbol, sub in per_symbol.items():
            try:
                row = _compute_row(symbol, sub)
                if row:
                    rows.append(row)
            except Exception as e:
                log.debug("Skipping %s: %s", symbol, e)
        time.sleep(RATE_LIMIT_DELAY)

    log.info(
        "Scan complete: %d rows / %d tickers (Alpaca returned data for %d)",
        len(rows), total, fetched_count,
    )
    return rows
