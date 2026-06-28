"""Unit tests for the grading change in scanner/performance.py:
excess-vs-SPY at log + eval, net + excess in rec/desk rollups, universe_segment
breakdown, and the extended HORIZONS=[1,3,5,10,21] drift horizons.

Stdlib unittest (pytest is not installed in .venv). Run with:
    .venv/bin/python -m unittest tests.test_grading -v

No network/Alpaca: performance._fetch_current_prices is monkeypatched and the
module-level *_LOG / *_FILE Path constants are pointed at a scratchpad tmp dir
so nothing touches data/ or the real cache.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scanner import performance as perf


def _iso_days_ago(days: float, now: datetime) -> str:
    return (now - timedelta(days=days)).isoformat()


class GradingTestBase(unittest.TestCase):
    """Redirect every log/file the module writes into a per-test tmp dir and
    stub the price fetch so no test ever hits the network."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        # Snapshot + override every module-level path so writes are isolated.
        self._saved_paths = {
            name: getattr(perf, name)
            for name in (
                "ALERTS_LOG", "PERFORMANCE_FILE", "RECS_LOG",
                "RECOMMENDATION_PERFORMANCE_FILE", "DESK_PERFORMANCE_FILE",
                "PREDICTIONS_LOG", "PREDICTION_PERFORMANCE_FILE", "LEDGER_FILE",
                "EARLY_ENTRY_LOG", "EARLY_ENTRY_PERFORMANCE_FILE",
            )
        }
        perf.ALERTS_LOG = tmp / "alerts_log.jsonl"
        perf.PERFORMANCE_FILE = tmp / "performance.json"
        perf.RECS_LOG = tmp / "recommendations_log.jsonl"
        perf.RECOMMENDATION_PERFORMANCE_FILE = tmp / "recommendation_performance.json"
        perf.DESK_PERFORMANCE_FILE = tmp / "desk_performance.json"
        perf.PREDICTIONS_LOG = tmp / "predictions_log.jsonl"
        perf.PREDICTION_PERFORMANCE_FILE = tmp / "prediction_performance.json"
        perf.LEDGER_FILE = tmp / "ledger.json"
        perf.EARLY_ENTRY_LOG = tmp / "early_entry_log.jsonl"
        perf.EARLY_ENTRY_PERFORMANCE_FILE = tmp / "early_entry_performance.json"

        self._saved_fetch = perf._fetch_current_prices
        self.now = datetime.now(timezone.utc)

    def tearDown(self) -> None:
        for name, val in self._saved_paths.items():
            setattr(perf, name, val)
        perf._fetch_current_prices = self._saved_fetch
        self._tmp.cleanup()

    def _write_recs(self, entries: list[dict]) -> None:
        with open(perf.RECS_LOG, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def _read_recs(self) -> list[dict]:
        return perf._read_entries(perf.RECS_LOG)


class TestConstants(GradingTestBase):
    def test_horizons_extended_and_early_unchanged(self):
        # T1: HORIZONS gains 10d/21d; EARLY_HORIZONS (imported by opening.py)
        # must stay byte-identical.
        self.assertEqual(perf.HORIZONS, [1, 3, 5, 10, 21])
        self.assertEqual(perf.EARLY_HORIZONS, [0, 1, 3])
        self.assertEqual(perf.SPY_SYMBOL, "SPY")


class TestSegment(GradingTestBase):
    def test_segment_large_vs_tail(self):
        # T2: in popular set -> large, else tail.
        popular = {"AAPL", "NVDA"}
        self.assertEqual(perf._segment("AAPL", popular), "large")
        self.assertEqual(perf._segment("RKLB", popular), "tail")
        # Empty (unbuilt universe) -> everything tail.
        self.assertEqual(perf._segment("AAPL", set()), "tail")


class TestHorizonStats(GradingTestBase):
    def test_legacy_shape_without_excess(self):
        # T3a: omitting the excess arg keeps the original shape exactly.
        s = perf._horizon_stats([2.0, -1.0])
        self.assertEqual(
            set(s.keys()),
            {"evaluated", "hit_rate", "avg_return_pct",
             "hit_rate_net", "avg_return_net_pct"},
        )
        # Net == gross minus slippage.
        self.assertAlmostEqual(s["avg_return_pct"], 0.5)
        self.assertAlmostEqual(s["avg_return_net_pct"], 0.5 - perf.SLIPPAGE_PCT)

    def test_excess_fields_and_none_skipping(self):
        # T3b: excess arg adds avg_excess_pct/hit_rate_excess; None skipped.
        s = perf._horizon_stats([6.0, 4.0, 1.0], excess=[4.0, None, -1.0])
        # mean of [4.0, -1.0] = 1.5
        self.assertAlmostEqual(s["avg_excess_pct"], 1.5)
        # 1 of 2 non-None excess > 0
        self.assertAlmostEqual(s["hit_rate_excess"], 0.5)

    def test_excess_all_none_is_none(self):
        s = perf._horizon_stats([1.0], excess=[None])
        self.assertIsNone(s["avg_excess_pct"])
        self.assertIsNone(s["hit_rate_excess"])

    def test_empty_with_excess_arg(self):
        s = perf._horizon_stats([], excess=[])
        self.assertEqual(s["evaluated"], 0)
        self.assertIsNone(s["avg_excess_pct"])
        self.assertIsNone(s["hit_rate_excess"])
        self.assertIsNone(s["avg_return_net_pct"])


class TestExcessEndToEnd(GradingTestBase):
    def test_excess_math_via_evaluate(self):
        # T4: one AAPL long, picked 4 days ago at 100 with SPY at 500.
        # Live snapshot: AAPL 106, SPY 510 -> stock +6%, SPY +2%, excess +4%.
        self._write_recs([{
            "ts": _iso_days_ago(4, self.now),
            "ticker": "AAPL",
            "direction": "long",
            "price_at_pick": 100.0,
            "spy_price_at_pick": 500.0,
            "evaluations": {},
        }])
        perf._fetch_current_prices = lambda client, tickers: {"AAPL": 106.0, "SPY": 510.0}
        perf.evaluate_pending_recommendations(object(), self.now)

        ev = self._read_recs()[0]["evaluations"]
        for hd in ("1d", "3d"):
            self.assertIn(hd, ev)
            self.assertAlmostEqual(ev[hd]["signed_return_pct"], 6.0)
            self.assertAlmostEqual(ev[hd]["spy_return_pct"], 2.0)
            self.assertAlmostEqual(ev[hd]["excess_return_pct"], 4.0)
        # 10d/21d not yet crossed (only 4 days old).
        self.assertNotIn("10d", ev)
        self.assertNotIn("21d", ev)

    def test_short_excess_sign(self):
        # Short pick: SPY excess is computed off the SIGNED stock return.
        # AAPL short from 100 -> 95 = signed +5; SPY 500->505 = +1; excess +4.
        self._write_recs([{
            "ts": _iso_days_ago(2, self.now),
            "ticker": "AAPL",
            "direction": "short",
            "price_at_pick": 100.0,
            "spy_price_at_pick": 500.0,
            "evaluations": {},
        }])
        perf._fetch_current_prices = lambda client, tickers: {"AAPL": 95.0, "SPY": 505.0}
        perf.evaluate_pending_recommendations(object(), self.now)
        ev = self._read_recs()[0]["evaluations"]["1d"]
        self.assertAlmostEqual(ev["signed_return_pct"], 5.0)
        self.assertAlmostEqual(ev["spy_return_pct"], 1.0)
        self.assertAlmostEqual(ev["excess_return_pct"], 4.0)

    def test_legacy_row_without_spy_price_skips_excess(self):
        # No spy_price_at_pick -> stock leg graded, excess silently omitted.
        self._write_recs([{
            "ts": _iso_days_ago(2, self.now),
            "ticker": "AAPL",
            "direction": "long",
            "price_at_pick": 100.0,
            "evaluations": {},
        }])
        perf._fetch_current_prices = lambda client, tickers: {"AAPL": 110.0, "SPY": 510.0}
        perf.evaluate_pending_recommendations(object(), self.now)
        ev = self._read_recs()[0]["evaluations"]["1d"]
        self.assertAlmostEqual(ev["signed_return_pct"], 10.0)
        self.assertNotIn("excess_return_pct", ev)
        self.assertNotIn("spy_return_pct", ev)


class TestPointInTime(GradingTestBase):
    def test_settled_horizon_not_reevaluated(self):
        # T5: a horizon already present is never recomputed (point-in-time).
        sentinel = {"price": 999.0, "return_pct": 99.0, "signed_return_pct": 99.0}
        self._write_recs([{
            "ts": _iso_days_ago(4, self.now),
            "ticker": "AAPL",
            "direction": "long",
            "price_at_pick": 100.0,
            "spy_price_at_pick": 500.0,
            "evaluations": {"1d": dict(sentinel)},
        }])
        perf._fetch_current_prices = lambda client, tickers: {"AAPL": 106.0, "SPY": 510.0}
        perf.evaluate_pending_recommendations(object(), self.now)
        ev = self._read_recs()[0]["evaluations"]
        self.assertEqual(ev["1d"], sentinel)  # untouched
        self.assertIn("3d", ev)               # newly crossed horizon recorded


class TestAlertsBytesIdentical(GradingTestBase):
    def test_alerts_path_has_no_spy_leg(self):
        # bench_key defaults None for alerts -> no SPY symbol leaks into the
        # eval dict even if SPY happens to be priced.
        with open(perf.ALERTS_LOG, "w") as f:
            f.write(json.dumps({
                "ts": _iso_days_ago(2, self.now),
                "ticker": "AAPL",
                "type": "big_move",
                "price_at_alert": 100.0,
                "direction": 1,
                "evaluations": {},
            }) + "\n")
        perf._fetch_current_prices = lambda client, tickers: {"AAPL": 110.0, "SPY": 510.0}
        perf.evaluate_pending(object(), self.now)
        ev = perf._read_entries(perf.ALERTS_LOG)[0]["evaluations"]["1d"]
        self.assertEqual(set(ev.keys()), {"price", "return_pct", "signed_return_pct"})


class TestRecommendationStats(GradingTestBase):
    def test_per_bucket_and_per_segment_net_excess(self):
        # T6: pick A large/long/hi WITH excess; pick B tail/long/lo WITHOUT.
        self._write_recs([
            {
                "ts": _iso_days_ago(5, self.now),
                "ticker": "AAPL", "direction": "long", "score": 9,
                "universe_segment": "large",
                "price_at_pick": 100.0, "spy_price_at_pick": 500.0,
                "evaluations": {"1d": {
                    "price": 106.0, "return_pct": 6.0,
                    "signed_return_pct": 6.0,
                    "spy_return_pct": 2.0, "excess_return_pct": 4.0,
                }},
            },
            {
                "ts": _iso_days_ago(5, self.now),
                "ticker": "RKLB", "direction": "long", "score": 3,
                "universe_segment": "tail",
                "price_at_pick": 20.0,
                "evaluations": {"1d": {
                    "price": 21.0, "return_pct": 5.0, "signed_return_pct": 5.0,
                }},
            },
        ])
        out = perf.compile_recommendation_stats(self.now)

        # Top-level slippage echoed.
        self.assertEqual(out["slippage_round_trip_pct"], perf.SLIPPAGE_PCT)

        # per_bucket: both gross AND net present (net was missing before).
        hi_horizons = out["per_bucket"]["long_hi"]["horizons"]
        a = hi_horizons["1d"]
        self.assertAlmostEqual(a["avg_return_pct"], 6.0)
        self.assertAlmostEqual(a["avg_return_net_pct"], 6.0 - perf.SLIPPAGE_PCT)
        self.assertAlmostEqual(a["avg_excess_pct"], 4.0)
        self.assertAlmostEqual(a["hit_rate_excess"], 1.0)

        b = out["per_bucket"]["long_lo"]["horizons"]["1d"]
        self.assertAlmostEqual(b["avg_return_pct"], 5.0)
        self.assertIsNone(b["avg_excess_pct"])  # no SPY leg logged

        # per_segment is a NEW sibling with large/tail direction buckets.
        self.assertIn("per_segment", out)
        self.assertIn("long_large", out["per_segment"])
        self.assertIn("long_tail", out["per_segment"])
        self.assertAlmostEqual(
            out["per_segment"]["long_large"]["horizons"]["1d"]["avg_excess_pct"], 4.0)

        # 10d/21d horizons exist (extended drift) even with no data.
        self.assertIn("10d", hi_horizons)
        self.assertIn("21d", hi_horizons)
        self.assertEqual(hi_horizons["21d"]["evaluated"], 0)

    def test_missing_segment_defaults_tail(self):
        # A row without universe_segment falls into the tail bucket.
        self._write_recs([{
            "ts": _iso_days_ago(5, self.now),
            "ticker": "FOO", "direction": "long", "score": 9,
            "price_at_pick": 10.0,
            "evaluations": {"1d": {"price": 11.0, "return_pct": 10.0, "signed_return_pct": 10.0}},
        }])
        out = perf.compile_recommendation_stats(self.now)
        self.assertIn("long_tail", out["per_segment"])


class TestDeskStats(GradingTestBase):
    def test_desk_net_excess_and_edges(self):
        # T7: a 'take' winner and a 'pass' loser, both with excess legs.
        self._write_recs([
            {
                "ts": _iso_days_ago(5, self.now),
                "ticker": "AAPL", "direction": "long", "score": 9,
                "universe_segment": "large",
                "price_at_pick": 100.0, "spy_price_at_pick": 500.0,
                "desk": {"decision": "take", "size": "full",
                          "agreement": "unanimous", "risk_veto": False},
                "evaluations": {"1d": {
                    "price": 108.0, "return_pct": 8.0, "signed_return_pct": 8.0,
                    "spy_return_pct": 2.0, "excess_return_pct": 6.0,
                }},
            },
            {
                "ts": _iso_days_ago(5, self.now),
                "ticker": "RKLB", "direction": "long", "score": 8,
                "universe_segment": "tail",
                "price_at_pick": 20.0, "spy_price_at_pick": 500.0,
                "desk": {"decision": "pass", "size": "none",
                          "agreement": "split", "risk_veto": True},
                "evaluations": {"1d": {
                    "price": 19.0, "return_pct": -5.0, "signed_return_pct": -5.0,
                    "spy_return_pct": 2.0, "excess_return_pct": -7.0,
                }},
            },
        ])
        out = perf.compile_desk_stats(self.now)

        take = out["by_decision"]["take"]["horizons"]["1d"]
        self.assertAlmostEqual(take["avg_return_pct"], 8.0)
        self.assertAlmostEqual(take["avg_return_net_pct"], 8.0 - perf.SLIPPAGE_PCT)
        self.assertAlmostEqual(take["avg_excess_pct"], 6.0)

        # Gross edge still emitted, plus net and excess siblings.
        self.assertIn("take_minus_pass_edge", out)
        self.assertIn("take_minus_pass_edge_net", out)
        self.assertIn("take_minus_pass_edge_excess", out)
        # take 8 − pass(−5) = 13 gross
        self.assertAlmostEqual(out["take_minus_pass_edge"]["1d"], 13.0)
        # take 6 − pass(−7) = 13 excess
        self.assertAlmostEqual(out["take_minus_pass_edge_excess"]["1d"], 13.0)

    def test_edge_none_when_one_side_missing(self):
        # Only a 'take' bucket -> edge is None (no 'pass' to compare).
        self._write_recs([{
            "ts": _iso_days_ago(2, self.now),
            "ticker": "AAPL", "direction": "long", "score": 9,
            "price_at_pick": 100.0, "spy_price_at_pick": 500.0,
            "desk": {"decision": "take", "agreement": "unanimous", "risk_veto": False},
            "evaluations": {"1d": {
                "price": 105.0, "return_pct": 5.0, "signed_return_pct": 5.0,
                "spy_return_pct": 1.0, "excess_return_pct": 4.0,
            }},
        }])
        out = perf.compile_desk_stats(self.now)
        self.assertIsNone(out["take_minus_pass_edge"]["1d"])
        self.assertIsNone(out["take_minus_pass_edge_excess"]["1d"])


class TestLedgerExtendedHorizons(GradingTestBase):
    def test_ledger_outcomes_have_10d_21d(self):
        # T8: outcomes comprehension iterates HORIZONS -> 10d/21d auto-appear;
        # status still derives from 1d.
        self._write_recs([{
            "ts": _iso_days_ago(22, self.now),
            "ticker": "AAPL", "direction": "long", "score": 9,
            "price_at_pick": 100.0, "spy_price_at_pick": 500.0,
            "evaluations": {
                "1d": {"price": 101.0, "return_pct": 1.0, "signed_return_pct": 1.0},
                "10d": {"price": 110.0, "return_pct": 10.0, "signed_return_pct": 10.0},
                "21d": {"price": 121.0, "return_pct": 21.0, "signed_return_pct": 21.0},
            },
        }])
        payload = perf.write_ledger(self.now)
        pick = next(e for e in payload["entries"] if e["kind"] == "pick")
        self.assertIn("10d", pick["outcomes"])
        self.assertIn("21d", pick["outcomes"])
        self.assertEqual(pick["outcomes"]["10d"], 10.0)
        self.assertEqual(pick["status"], "hit")  # from 1d > 0


class TestEmptyPricesNoOp(GradingTestBase):
    def test_no_prices_leaves_log_untouched(self):
        # T9: empty fetch -> early return, log bytes unchanged.
        entry = {
            "ts": _iso_days_ago(4, self.now),
            "ticker": "AAPL", "direction": "long",
            "price_at_pick": 100.0, "spy_price_at_pick": 500.0,
            "evaluations": {},
        }
        self._write_recs([entry])
        before = perf.RECS_LOG.read_text()
        perf._fetch_current_prices = lambda client, tickers: {}
        perf.evaluate_pending_recommendations(object(), self.now)
        self.assertEqual(perf.RECS_LOG.read_text(), before)


class TestLogRecommendations(GradingTestBase):
    def test_log_writes_spy_price_and_segment(self):
        # log_recommendations stamps spy_price_at_pick (from regime) +
        # universe_segment (from popular()) on each entry.
        saved_popular = None
        from scanner import universe as uni
        saved_popular = uni.popular
        uni.popular = lambda: {"AAPL"}
        try:
            recs = {"longs": [{"ticker": "AAPL", "direction": "long", "score": 9,
                               "reasons": ["r1"]}],
                    "shorts": [{"ticker": "RKLB", "direction": "short", "score": 8,
                                "reasons": ["r2"]}]}
            rows = [{"ticker": "AAPL", "price": 100.0},
                    {"ticker": "RKLB", "price": 20.0}]
            perf.log_recommendations(recs, rows, self.now, regime={"spy_price": 500.0})
        finally:
            uni.popular = saved_popular

        logged = {e["ticker"]: e for e in self._read_recs()}
        self.assertEqual(logged["AAPL"]["spy_price_at_pick"], 500.0)
        self.assertEqual(logged["AAPL"]["universe_segment"], "large")
        self.assertEqual(logged["RKLB"]["universe_segment"], "tail")

    def test_log_without_regime_stores_none_spy(self):
        from scanner import universe as uni
        saved_popular = uni.popular
        uni.popular = lambda: set()
        try:
            recs = {"longs": [{"ticker": "AAPL", "direction": "long", "score": 9,
                               "reasons": ["r1"]}]}
            rows = [{"ticker": "AAPL", "price": 100.0}]
            perf.log_recommendations(recs, rows, self.now, regime=None)
        finally:
            uni.popular = saved_popular
        e = self._read_recs()[0]
        self.assertIsNone(e["spy_price_at_pick"])
        self.assertEqual(e["universe_segment"], "tail")  # empty universe


if __name__ == "__main__":
    unittest.main()
