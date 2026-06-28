"""Unit tests for scanner.backtest on SYNTHETIC daily bars.

No network, no local-bar dependency: every frame is generated here. pytest is
not installed in this venv, so these are stdlib unittest. Run with:
    .venv/bin/python -m unittest tests.test_backtest -v
"""
from __future__ import annotations

import math
import random
import unittest

import pandas as pd

from scanner import backtest, performance, recommend


def _bars(prices: list[float], volumes: list[float], start="2025-01-01") -> pd.DataFrame:
    """OHLCV frame from close + volume lists (OHLC flat around close)."""
    idx = pd.bdate_range(start=start, periods=len(prices))
    close = pd.Series(prices, index=idx)
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close),
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": pd.Series(volumes, index=idx),
        }
    )


def _random_walk(n: int, seed: int, p0: float = 50.0, vol: float = 1_000_000.0):
    rng = random.Random(seed)
    prices, volumes = [p0], [vol]
    for _ in range(n - 1):
        prices.append(max(3.5, prices[-1] * (1 + rng.gauss(0, 0.012))))
        volumes.append(max(120_000, vol * (1 + rng.gauss(0, 0.25))))
    return prices, volumes


def _engineered_long() -> pd.DataFrame:
    """A *realistic* momentum long the scorer should fire on: a healthy uptrend
    (drift up with periodic pullbacks so RSI stays in the trend zone, NOT a
    parabolic RSI-100 chase the scorer correctly rejects), then a ~3% breakout
    on a volume spike = the entry, then follow-through so horizons grade up."""
    prices, volumes = [20.0], [500_000.0]
    for k in range(1, 55):
        prices.append(prices[-1] * (0.99 if k % 3 == 0 else 1.012))  # pullback every 3rd
        volumes.append(500_000.0)
    prices.append(prices[-1] * 1.03)        # breakout bar
    volumes.append(1_350_000.0)             # ~2.7x relative volume
    for _ in range(22):                     # follow-through for the 21d horizon
        prices.append(prices[-1] * 1.008)
        volumes.append(800_000.0)
    return _bars(prices, volumes)


class TestFeatureFrame(unittest.TestCase):
    def test_features_match_technicals_math(self):
        """Vectorized last-bar features equal scanner.technicals on same bars."""
        from scanner import technicals

        prices, volumes = _random_walk(80, seed=7)
        bars = _bars(prices, volumes)
        feat = backtest.feature_frame(bars)
        self.assertFalse(feat.empty)

        last = feat.iloc[-1]
        # technicals computes last-bar RSI/MACD from the same close series.
        close = bars["Close"].astype(float)
        self.assertAlmostEqual(last["rsi_14"], technicals._rsi(close), places=4)
        macd_hist, macd_cross = technicals._macd(close)
        self.assertAlmostEqual(last["macd_hist"], macd_hist, places=6)
        self.assertEqual(
            last["macd_cross"] if isinstance(last["macd_cross"], str) else None,
            macd_cross,
        )
        # pct_1d matches the live (last/prev - 1) * 100.
        exp_pct1 = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
        self.assertAlmostEqual(last["pct_1d"], exp_pct1, places=6)

    def test_price_floor_drops_penny_bars(self):
        """Closes below config.MIN_PRICE are filtered like the live path."""
        from scanner import config

        n = 60
        prices = [config.MIN_PRICE - 1.0] * n  # all sub-floor
        volumes = [500_000.0] * n
        feat = backtest.feature_frame(_bars(prices, volumes))
        self.assertTrue(feat.empty)


class TestRowConstruction(unittest.TestCase):
    def test_row_has_no_phantom_synthesis(self):
        """Backtest rows are pure-technical: no synthesis/intraday/news keys."""
        prices, volumes = _random_walk(70, seed=11)
        feat = backtest.feature_frame(_bars(prices, volumes))
        row = backtest._row_from_features("ABC", feat.iloc[-1])
        for absent in ("synthesis", "intraday", "news_count", "caution_level"):
            self.assertNotIn(absent, row)
        # And the scorer accepts it without raising.
        recommend._score_row(row, "long")  # must not raise

    def test_nan_features_become_none(self):
        s = pd.Series(
            {"pct_1d": float("nan"), "pct_5d": 2.0, "rel_volume": 1.0,
             "rsi_14": 50.0, "macd_hist": 0.0, "macd_cross": None}
        )
        row = backtest._row_from_features("X", s)
        self.assertIsNone(row["pct_1d"])
        self.assertIsNone(row["macd_cross"])


class TestSimulate(unittest.TestCase):
    def test_engineered_long_is_labelled_and_graded(self):
        """A clean uptrend + volume spike must surface as a long and get graded
        at every horizon, with sane bucket stats."""
        summary = backtest.simulate({"WIN": _engineered_long()})
        self.assertGreater(summary["n_entries"], 0)
        long_keys = [k for k in summary["buckets"] if k.startswith("long_")]
        self.assertTrue(long_keys, f"expected a long bucket, got {list(summary['buckets'])}")

        bucket = summary["buckets"][long_keys[0]]
        self.assertGreater(bucket["n"], 0)
        for h in performance.HORIZONS:
            stat = bucket["horizons"][f"{h}d"]
            # net is exactly gross minus the live slippage drag.
            if stat["avg_return_pct"] is not None:
                self.assertAlmostEqual(
                    stat["avg_return_net_pct"],
                    round(stat["avg_return_pct"] - performance.SLIPPAGE_PCT, 2),
                    places=2,
                )
                self.assertIsNotNone(stat["hit_rate"])
                self.assertGreaterEqual(stat["hit_rate"], 0.0)
                self.assertLessEqual(stat["hit_rate"], 1.0)
        # On a monotonic climb the long should be net-positive at 5d.
        self.assertGreater(bucket["horizons"]["5d"]["avg_return_pct"], 0.0)

    def test_horizons_and_slippage_are_inherited_not_redefined(self):
        """The harness must report the live grader's horizons + slippage."""
        self.assertEqual(backtest.HORIZONS, performance.HORIZONS)
        self.assertEqual(backtest.SLIPPAGE_PCT, performance.SLIPPAGE_PCT)
        prices, volumes = _random_walk(80, seed=3)
        summary = backtest.simulate({"RW": _bars(prices, volumes)})
        self.assertEqual(summary["horizons"], performance.HORIZONS)
        self.assertEqual(summary["slippage_round_trip_pct"], performance.SLIPPAGE_PCT)

    def test_excess_vs_spy_is_paired_window(self):
        """With a SPY frame, excess = pick return − SPY return over the SAME
        entry/exit bar offsets. Flat SPY → excess equals the pick's own return."""
        bars = _engineered_long()
        # Flat SPY (0% every window) on the SAME calendar length.
        spy = _bars([100.0] * len(bars), [80_000_000.0] * len(bars))

        summary = backtest.simulate({"WIN": bars}, spy_bars=spy)
        bucket = next(b for k, b in summary["buckets"].items() if k.startswith("long_"))
        for h in performance.HORIZONS:
            stat = bucket["horizons"][f"{h}d"]
            if stat["avg_excess_pct"] is not None:
                # flat bench → excess avg == gross avg (SPY contributes 0).
                self.assertAlmostEqual(
                    stat["avg_excess_pct"], stat["avg_return_pct"], places=2
                )
                self.assertIsNotNone(stat["hit_rate_excess"])

    def test_excess_is_none_without_spy(self):
        prices, volumes = _random_walk(80, seed=9)
        summary = backtest.simulate({"RW": _bars(prices, volumes)})
        for bucket in summary["buckets"].values():
            for stat in bucket["horizons"].values():
                self.assertIsNone(stat["avg_excess_pct"])
                self.assertIsNone(stat["hit_rate_excess"])

    def test_spy_symbol_is_not_traded(self):
        """A bar set named SPY is the benchmark, never a labelled entry."""
        prices, volumes = _random_walk(80, seed=2)
        summary = backtest.simulate({backtest.SPY_SYMBOL: _bars(prices, volumes)})
        self.assertEqual(summary["n_entries"], 0)
        self.assertEqual(summary["buckets"], {})

    def test_short_history_is_skipped(self):
        prices, volumes = _random_walk(20, seed=1)  # < MIN_LOOKBACK + 1
        summary = backtest.simulate({"TINY": _bars(prices, volumes)})
        self.assertEqual(summary["n_entries"], 0)

    def test_runs_over_a_small_universe_fast(self):
        """Many random-walk symbols still complete quickly and aggregate."""
        import time

        bars_by = {f"SY{i}": _bars(*_random_walk(120, seed=i)) for i in range(25)}
        t0 = time.time()
        summary = backtest.simulate(bars_by)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 20.0, f"backtest too slow: {elapsed:.1f}s")
        self.assertEqual(summary["n_symbols"], 25)
        # Every bucket key is a valid direction_band combo.
        for key in summary["buckets"]:
            direction, band = key.split("_")
            self.assertIn(direction, ("long", "short"))
            self.assertIn(band, ("high", "standard"))


class TestRunDiscovery(unittest.TestCase):
    def test_run_on_empty_root_returns_sentinel(self):
        """No bars on disk → graceful, structured no-op (not a crash)."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            out = backtest.run(root=d)
        self.assertEqual(out["n_entries"], 0)
        self.assertEqual(out["buckets"], {})
        self.assertIn("note", out)
        self.assertEqual(out["horizons"], performance.HORIZONS)

    def test_discover_and_run_synthetic_csv(self):
        """Drop a synthetic OHLCV CSV under data/ and confirm discovery+grade."""
        import tempfile
        from pathlib import Path

        bars = _engineered_long()

        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d) / "data"
            data_dir.mkdir()
            out_csv = bars.reset_index().rename(columns={"index": "date"})
            out_csv.to_csv(data_dir / "WIN.csv", index=False)
            found = backtest.discover_bars(root=d)
            self.assertIn("WIN", found)
            summary = backtest.run(root=d)
        self.assertGreater(summary["n_entries"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
