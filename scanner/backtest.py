"""Vectorized momentum backtester (Contract F).

Replays the live recommendation scorer over historical daily bars and grades
every labelled entry at the SAME horizons / slippage the live desk uses, so a
backtest bucket is directly comparable to data/recommendation_performance.json.

The point is fidelity, not a second strategy: features are recomputed from raw
OHLCV with the identical RSI/MACD/relative-volume math as scanner.technicals,
the resulting row is handed verbatim to scanner.recommend._score_row, and
exits/slippage come from scanner.performance (HORIZONS, SLIPPAGE_PCT) — never
redefined here. What daily bars cannot supply (intraday VWAP, an LLM news
synthesis) is simply absent from the row, exactly as _score_row already
tolerates; a backtest is therefore the pure price/volume floor of the live
signal, honestly labelled as such.

No network/API: bars are read from disk (data/ or stocks/) or passed in. When
no local bars exist the module still imports and runs — the unit test drives it
on synthetic random-walk bars. Runs in minutes: each symbol is a single pass
with cached rolling indicators.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pandas as pd

from scanner import config, performance, recommend

log = logging.getLogger(__name__)

# Exits + drag come from the live grader so backtest buckets line up with the
# production ledger; do NOT redefine these here.
HORIZONS = performance.HORIZONS          # [1, 3, 5, 10, 21] once Grading lands
SLIPPAGE_PCT = performance.SLIPPAGE_PCT  # flat round-trip drag, %
HIGH_SCORE = performance.HIGH_SCORE      # score >= this → "high" conviction band

# A backtest needs enough history to seed MACD (35 bars) plus a horizon of
# forward bars to grade against; mirror technicals' minimum lookback.
MIN_LOOKBACK = 35
# Local bar discovery: a CSV per symbol named <TICKER>.csv with OHLCV columns.
BAR_DIRS = ("data/bars", "data/history", "stocks/bars", "data")
SPY_SYMBOL = performance.SPY_SYMBOL if hasattr(performance, "SPY_SYMBOL") else "SPY"


# --------------------------------------------------------------------------
# Feature extraction — same indicators as scanner.technicals, but vectorized
# across every bar so one pass yields a feature row for every historical day.
# --------------------------------------------------------------------------
def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI for the whole series (technicals._rsi gives only the last)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(avg_loss != 0, 100.0)  # all-gain window → RSI 100
    return rsi


def _macd_frame(close: pd.Series) -> pd.DataFrame:
    """MACD histogram + per-bar cross label, matching technicals._macd."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    prev = hist.shift(1)
    cross = pd.Series(None, index=close.index, dtype=object)
    cross = cross.mask((prev <= 0) & (hist > 0), "bullish")
    cross = cross.mask((prev >= 0) & (hist < 0), "bearish")
    return pd.DataFrame({"macd_hist": hist, "macd_cross": cross})


def feature_frame(bars: pd.DataFrame) -> pd.DataFrame:
    """Vectorize the scanner.technicals row features over an OHLCV frame.

    `bars` is indexed by date with Close/Volume columns (case-insensitive).
    Returns one feature row per bar with the keys scanner.recommend._score_row
    consumes: pct_1d, pct_5d, rel_volume, rsi_14, macd_hist, macd_cross. The
    raw close is kept (for exit pricing) and rows lacking the 20-bar volume /
    MACD warmup are dropped, exactly as the live path would skip them.
    """
    cols = {c.lower(): c for c in bars.columns}
    close = bars[cols["close"]].astype(float)
    volume = bars[cols["volume"]].astype(float)

    pct_1d = close.pct_change(1) * 100
    pct_5d = close.pct_change(5) * 100
    avg_vol_20 = volume.shift(1).rolling(20).mean()  # prior 20 bars, excl. today
    rel_volume = volume / avg_vol_20

    rsi = _rsi_series(close)
    macd = _macd_frame(close)

    feat = pd.DataFrame(
        {
            "close": close,
            "pct_1d": pct_1d,
            "pct_5d": pct_5d,
            "rel_volume": rel_volume,
            "rsi_14": rsi,
            "macd_hist": macd["macd_hist"],
            "macd_cross": macd["macd_cross"],
        }
    )
    # Need a real MACD seed and a defined relative-volume to mirror the live row.
    feat = feat.iloc[MIN_LOOKBACK:]
    feat = feat[feat["rel_volume"].notna() & feat["close"].notna()]
    # Liquidity / price floor (config), same as technicals._compute_row gates.
    feat = feat[feat["close"] >= config.MIN_PRICE]
    return feat


def _row_from_features(ticker: str, frow: pd.Series) -> dict:
    """Build the scanner.recommend row dict from one feature row.

    Only price/volume features are populated — `synthesis`, `intraday`,
    `news_count` and `caution_level` are intentionally absent, the same shape
    _score_row already handles for a pure-technical pick. None-out NaNs so the
    scorer's `is not None` guards behave like the live path.
    """
    def _clean(v):
        return None if (v is None or (isinstance(v, float) and math.isnan(v))) else v

    return {
        "ticker": ticker,
        "pct_1d": _clean(round(float(frow["pct_1d"]), 2)),
        "pct_5d": _clean(round(float(frow["pct_5d"]), 2)),
        "rel_volume": _clean(round(float(frow["rel_volume"]), 2)),
        "rsi_14": _clean(round(float(frow["rsi_14"]), 1)),
        "macd_hist": _clean(round(float(frow["macd_hist"]), 3)),
        "macd_cross": frow["macd_cross"] if isinstance(frow["macd_cross"], str) else None,
    }


def _band(score: int) -> str:
    """High-conviction vs standard, on the same HIGH_SCORE cut as performance."""
    return "high" if score >= HIGH_SCORE else "standard"


def _empty_bucket() -> dict:
    return {"n": 0, "returns": {h: [] for h in HORIZONS}, "excess": {h: [] for h in HORIZONS}}


def simulate(
    bars_by_ticker: dict[str, pd.DataFrame],
    spy_bars: pd.DataFrame | None = None,
    regime: dict | None = None,
) -> dict:
    """Replay the scorer over every symbol's history and grade each entry.

    For every bar that scanner.recommend._score_row labels a long or short, the
    entry is the bar's close and the exit is the close `h` bars later (h in
    HORIZONS), signed by direction and net of nothing here — gross and
    net-of-SLIPPAGE are both reported at roll-up. When `spy_bars` is given the
    bench leg uses the SAME entry/exit bar offsets, so excess_vs_SPY is the
    point-in-time outperformance of the pick over that holding window.

    Returns a dict keyed "{direction}_{band}" of grading buckets plus a
    machine-readable summary. Pure in-memory; no I/O, no network.
    """
    buckets: dict[str, dict] = {}
    spy_close = None
    if spy_bars is not None and len(spy_bars):
        cols = {c.lower(): c for c in spy_bars.columns}
        spy_close = spy_bars[cols["close"]].astype(float)

    n_entries = 0
    for ticker, bars in bars_by_ticker.items():
        if ticker == SPY_SYMBOL:
            continue
        if bars is None or len(bars) < MIN_LOOKBACK + 1:
            continue
        feat = feature_frame(bars)
        if feat.empty:
            continue
        cols = {c.lower(): c for c in bars.columns}
        close = bars[cols["close"]].astype(float)
        close_pos = {idx: i for i, idx in enumerate(close.index)}
        n_close = len(close)

        for entry_date, frow in feat.iterrows():
            i = close_pos.get(entry_date)
            if i is None:
                continue
            entry_px = float(close.iloc[i])
            if entry_px <= 0:
                continue
            row = _row_from_features(ticker, frow)
            for direction in ("long", "short"):
                rec = recommend._score_row(row, direction)
                if not rec:
                    continue
                n_entries += 1
                key = f"{direction}_{_band(rec['score'])}"
                bucket = buckets.setdefault(key, _empty_bucket())
                bucket["n"] += 1
                sign = 1.0 if direction == "long" else -1.0
                for h in HORIZONS:
                    j = i + h
                    if j >= n_close:
                        continue
                    exit_px = float(close.iloc[j])
                    if exit_px <= 0:
                        continue
                    signed = (exit_px / entry_px - 1) * 100 * sign
                    bucket["returns"][h].append(signed)
                    if spy_close is not None and entry_date in spy_close.index:
                        sp_pos = spy_close.index.get_loc(entry_date)
                        if isinstance(sp_pos, int) and sp_pos + h < len(spy_close):
                            spy_in = float(spy_close.iloc[sp_pos])
                            spy_out = float(spy_close.iloc[sp_pos + h])
                            if spy_in > 0:
                                spy_ret = (spy_out / spy_in - 1) * 100
                                bucket["excess"][h].append(signed - spy_ret)

    summary = {
        "horizons": HORIZONS,
        "slippage_round_trip_pct": SLIPPAGE_PCT,
        "n_entries": n_entries,
        "n_symbols": sum(1 for t in bars_by_ticker if t != SPY_SYMBOL),
        "buckets": {key: _bucket_stats(b) for key, b in sorted(buckets.items())},
    }
    return summary


def _bucket_stats(bucket: dict) -> dict:
    """Per-horizon hit_rate / avg_return (gross+net) / excess_vs_SPY for one
    bucket. Net applies the live SLIPPAGE_PCT drag; excess is vs the paired SPY
    window (null when no SPY bars were supplied)."""
    out = {"n": bucket["n"], "horizons": {}}
    for h in HORIZONS:
        rets = bucket["returns"][h]
        exc = bucket["excess"][h]
        if rets:
            net = [r - SLIPPAGE_PCT for r in rets]
            stat = {
                "evaluated": len(rets),
                "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets), 3),
                "avg_return_pct": round(sum(rets) / len(rets), 2),
                "hit_rate_net": round(sum(1 for r in net if r > 0) / len(net), 3),
                "avg_return_net_pct": round(sum(net) / len(net), 2),
            }
        else:
            stat = {
                "evaluated": 0,
                "hit_rate": None, "avg_return_pct": None,
                "hit_rate_net": None, "avg_return_net_pct": None,
            }
        if exc:
            stat["avg_excess_pct"] = round(sum(exc) / len(exc), 2)
            stat["hit_rate_excess"] = round(sum(1 for e in exc if e > 0) / len(exc), 3)
        else:
            stat["avg_excess_pct"] = None
            stat["hit_rate_excess"] = None
        out["horizons"][f"{h}d"] = stat
    return out


# --------------------------------------------------------------------------
# Local bar loading — best-effort; returns {} when no bars are on disk.
# --------------------------------------------------------------------------
def _load_csv_bars(path: Path) -> pd.DataFrame | None:
    """Read a per-symbol OHLCV CSV; require Close + Volume columns."""
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    lower = {c.lower(): c for c in df.columns}
    if "close" not in lower or "volume" not in lower:
        return None
    for date_col in ("date", "timestamp", "t"):
        if date_col in lower:
            try:
                df = df.set_index(pd.to_datetime(df[lower[date_col]]))
            except Exception:
                pass
            break
    return df


def discover_bars(root: str | Path = ".") -> dict[str, pd.DataFrame]:
    """Find <TICKER>.csv OHLCV files under the known BAR_DIRS.

    Returns {ticker: frame}; empty dict when nothing is on disk (the harness
    then has nothing to run on — see the unit test for the synthetic path).
    """
    root = Path(root)
    out: dict[str, pd.DataFrame] = {}
    for rel in BAR_DIRS:
        d = root / rel
        if not d.is_dir():
            continue
        for csv in d.glob("*.csv"):
            df = _load_csv_bars(csv)
            if df is not None and len(df) >= MIN_LOOKBACK + 1:
                out[csv.stem.upper()] = df
    return out


def run(root: str | Path = ".", regime: dict | None = None) -> dict:
    """Discover local bars and backtest them. Returns the simulate() summary;
    a sentinel {"buckets": {}, "note": ...} when no bars are available."""
    bars = discover_bars(root)
    if not bars:
        log.warning("No local daily bars found under %s; nothing to backtest.", BAR_DIRS)
        return {
            "horizons": HORIZONS,
            "slippage_round_trip_pct": SLIPPAGE_PCT,
            "n_entries": 0,
            "n_symbols": 0,
            "buckets": {},
            "note": "no local bars discovered",
        }
    spy = bars.pop(SPY_SYMBOL, None)
    return simulate(bars, spy_bars=spy, regime=regime)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2))
