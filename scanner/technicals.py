"""Batched yfinance pull + technical indicators.

Produces one row per ticker with price, volume, RSI-14, MACD histogram,
percent change (1d/5d), and a relative-volume reading vs the 20d average.
Applies the liquidity + price floor here; tickers below the floor are dropped.
"""
from __future__ import annotations

import logging
import math
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from scanner import config

log = logging.getLogger(__name__)

BATCH_SIZE = 150
HISTORY_PERIOD = "3mo"


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


def _download_batch(tickers: list[str]) -> pd.DataFrame:
    return yf.download(
        tickers=tickers,
        period=HISTORY_PERIOD,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )


def scan(tickers: Iterable[str]) -> list[dict]:
    tickers = list(tickers)
    rows: list[dict] = []
    total = len(tickers)
    log.info("Scanning %d tickers in batches of %d", total, BATCH_SIZE)

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        try:
            df = _download_batch(batch)
        except Exception as e:
            log.warning("Batch %d failed (%s); falling back to per-ticker", i, e)
            df = None

        for t in batch:
            try:
                if df is None:
                    sub = yf.Ticker(t).history(period=HISTORY_PERIOD, auto_adjust=True)
                elif len(batch) == 1:
                    sub = df
                else:
                    sub = df[t] if t in df.columns.get_level_values(0) else None
                if sub is None or sub.empty:
                    continue
                row = _compute_row(t, sub)
                if row:
                    rows.append(row)
            except Exception as e:
                log.debug("Skipping %s: %s", t, e)

    log.info("Scan complete: %d tickers survived filters out of %d", len(rows), total)
    return rows
