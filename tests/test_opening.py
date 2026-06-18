"""Unit tests for scanner.opening — the early-entry catch-list tier.

Pure-logic + grading tests with synthetic rows and a mocked daily-bar fetch, so
they run without Alpaca / network. Run:  .venv/bin/python tests/test_opening.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import config, opening, performance, technicals, windows

ET = config.MARKET_TZ
PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def _row(ticker, *, prev, live, gap, vwap, hod, lod, above, bars=3,
         avg_vol=5_000_000, membership=("sp500",), rsi=60, caution=None,
         session_vol=2_000_000):
    spark = [round(prev * (1 + 0.001 * i), 2) for i in range(20)]  # ~flat near prev
    r = {
        "ticker": ticker,
        "price": prev,
        "pct_1d": round((live / prev - 1) * 100, 2),
        "pct_5d": 2.0,
        "avg_volume_20d": avg_vol,
        "rel_volume": 1.5,
        "rsi_14": rsi,
        "spark": spark,
        "membership": list(membership),
        "snapshot": {"live_price": live, "prev_close": prev, "gap_pct": gap},
        "intraday": {"vwap": vwap, "hod": hod, "lod": lod, "last": live,
                     "above_vwap": above, "bars": bars, "session_vol": session_vol},
    }
    if caution:
        r["caution_level"] = caution
    return r


def test_build():
    print("test_build (eligibility, firing gate, control cohort)")
    now = datetime(2026, 6, 15, 10, 0, tzinfo=ET)
    rows = [
        # fires long: gap +6, holding above VWAP (dist ~1.9%), small giveback
        _row("AAA", prev=100, live=106, gap=6.0, vwap=104, hod=107, lod=103, above=True),
        # eligible, not fired: blown off VWAP (dist ~5.8% > 3)
        _row("BBB", prev=100, live=110, gap=10.0, vwap=104, hod=111, lod=103, above=True),
        # eligible, not fired: 8% giveback from HOD
        _row("CCC", prev=100, live=103, gap=3.0, vwap=102, hod=112, lod=101, above=True),
        # fires short: gap -5, holding below VWAP
        _row("DDD", prev=100, live=95, gap=-5.0, vwap=97, hod=99, lod=94, above=False),
        # not eligible: illiquid + not an index member
        _row("EEE", prev=100, live=108, gap=8.0, vwap=105, hod=109, lod=103, above=True,
             avg_vol=400_000, membership=()),
        # not eligible: gap too small
        _row("FFF", prev=100, live=101.4, gap=1.4, vwap=100.5, hod=102, lod=100, above=True),
        # eligible, not fired: stretched
        _row("GGG", prev=100, live=104, gap=4.0, vwap=103, hod=105, lod=102, above=True,
             caution="stretched"),
    ]

    out = opening.build_catch_list(rows, regime=None, now=now, window=windows.Window.RTH)
    fired = {c["ticker"] for c in out["fired"]}
    passed = {c["ticker"] for c in out["eligible_passed"]}

    check("AAA fires long", "AAA" in fired)
    check("DDD fires short", "DDD" in fired)
    check("BBB eligible-passed (off VWAP)", "BBB" in passed and "BBB" not in fired)
    check("CCC eligible-passed (giveback)", "CCC" in passed and "CCC" not in fired)
    check("GGG eligible-passed (stretched)", "GGG" in passed and "GGG" not in fired)
    check("EEE excluded (illiquid)", "EEE" not in fired and "EEE" not in passed)
    check("FFF excluded (small gap)", "FFF" not in fired and "FFF" not in passed)
    check("_has_intraday True", out["_has_intraday"] is True)
    check("trading_date is ET date", out["trading_date"] == "2026-06-15")

    aaa = next(c for c in out["fired"] if c["ticker"] == "AAA")
    check("AAA direction long", aaa["direction"] == "long")
    check("AAA gap_band 5-8", aaa["gap_band"] == "5-8")
    check("AAA levels entry == live price", aaa["levels"]["entry"] == 106)
    check("AAA levels side long", aaa["levels"]["side"] == "long")
    check("AAA stop below entry", aaa["levels"]["stop"] < 106)
    check("AAA target above entry", aaa["levels"]["target"] > 106)
    check("AAA rvol_tod computed", aaa["rvol_tod"] is not None)

    ddd = next(c for c in out["fired"] if c["ticker"] == "DDD")
    check("DDD direction short", ddd["direction"] == "short")
    check("DDD levels side short", ddd["levels"]["side"] == "short")


def test_regime_suppresses_shorts():
    print("test_regime (bull tape suppresses shorts)")
    now = datetime(2026, 6, 15, 10, 0, tzinfo=ET)
    rows = [_row("DDD", prev=100, live=95, gap=-5.0, vwap=97, hod=99, lod=94, above=False)]
    out = opening.build_catch_list(rows, regime={"spy_above_50d": True},
                                   now=now, window=windows.Window.RTH)
    fired = {c["ticker"] for c in out["fired"]}
    passed = {c["ticker"] for c in out["eligible_passed"]}
    check("DDD short suppressed in bull regime", "DDD" not in fired and "DDD" in passed)


def test_no_intraday():
    print("test_no_intraday (retry guard)")
    now = datetime(2026, 6, 15, 10, 0, tzinfo=ET)
    r = _row("AAA", prev=100, live=106, gap=6.0, vwap=104, hod=107, lod=103, above=True, bars=0)
    r["intraday"] = {}  # no bars landed yet
    out = opening.build_catch_list([r], regime=None, now=now, window=windows.Window.RTH)
    check("_has_intraday False when no bars", out["_has_intraday"] is False)


def test_grading():
    print("test_grading (settled-close, [0,1,3] horizons, sign)")
    tmp = Path(tempfile.mkdtemp())
    log = tmp / "early_entry_log.jsonl"
    entry = {
        "ts": "2026-06-15T14:00:00+00:00",  # Mon 10:00 ET
        "ticker": "TST", "direction": "long", "fired": True,
        "price_at_entry": 100.0, "gap_pct": 6.0, "gap_band": "5-8",
        "score": 9.0, "thesis": "test", "evaluations": {},
    }
    log.write_text(json.dumps(entry) + "\n")

    # Synthetic daily closes: entry-day + next 3 trading days. Timestamps at
    # 05:00 UTC (≈01:00 ET) so the ET session date is preserved, like Alpaca's.
    idx = pd.to_datetime(
        ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"]
    ).tz_localize("UTC") + pd.Timedelta(hours=5)
    df = pd.DataFrame(
        {"Open": [0] * 4, "High": [0] * 4, "Low": [0] * 4,
         "Close": [102.0, 105.0, 103.0, 108.0], "Volume": [0] * 4},
        index=idx,
    )

    orig_fetch = technicals._fetch_batch
    orig_log = performance.EARLY_ENTRY_LOG
    technicals._fetch_batch = lambda syms, s, e: {"TST": df}
    performance.EARLY_ENTRY_LOG = log
    try:
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)  # Fri — all settled
        opening.evaluate_pending_early_entries(object(), now)
    finally:
        technicals._fetch_batch = orig_fetch
        performance.EARLY_ENTRY_LOG = orig_log

    graded = json.loads(log.read_text().splitlines()[0])
    ev = graded["evaluations"]
    check("0d graded (entry-day close)", ev.get("0d", {}).get("signed_return_pct") == 2.0)
    check("1d graded (+1 session)", ev.get("1d", {}).get("signed_return_pct") == 5.0)
    check("3d graded (+3 sessions)", ev.get("3d", {}).get("signed_return_pct") == 8.0)
    check("0d uses settled date", ev.get("0d", {}).get("date") == "2026-06-15")


def test_grading_short_sign_and_unsettled():
    print("test_grading (short sign + unsettled session not graded)")
    tmp = Path(tempfile.mkdtemp())
    log = tmp / "early_entry_log.jsonl"
    entry = {
        "ts": "2026-06-15T14:00:00+00:00", "ticker": "SHT", "direction": "short",
        "fired": True, "price_at_entry": 100.0, "evaluations": {},
    }
    log.write_text(json.dumps(entry) + "\n")
    idx = pd.to_datetime(["2026-06-15", "2026-06-16"]).tz_localize("UTC") + pd.Timedelta(hours=5)
    df = pd.DataFrame(
        {"Open": [0] * 2, "High": [0] * 2, "Low": [0] * 2, "Close": [95.0, 90.0], "Volume": [0] * 2},
        index=idx,
    )
    orig_fetch, orig_log = technicals._fetch_batch, performance.EARLY_ENTRY_LOG
    technicals._fetch_batch = lambda syms, s, e: {"SHT": df}
    performance.EARLY_ENTRY_LOG = log
    try:
        # "Today" is 06-16 ET → 06-16 is the current (unsettled) session, must
        # NOT be graded; only the past 06-15 close should be.
        now = datetime(2026, 6, 16, 18, 0, tzinfo=timezone.utc)
        opening.evaluate_pending_early_entries(object(), now)
    finally:
        technicals._fetch_batch, performance.EARLY_ENTRY_LOG = orig_fetch, orig_log

    ev = json.loads(log.read_text().splitlines()[0])["evaluations"]
    # short: price dropped 100→95 → +5% in the trade's favor
    check("short 0d signed +5", ev.get("0d", {}).get("signed_return_pct") == 5.0)
    check("unsettled 1d not graded", "1d" not in ev)


def test_compile_edge():
    print("test_compile (fired vs control edge)")
    tmp = Path(tempfile.mkdtemp())
    log = tmp / "early_entry_log.jsonl"
    perf = tmp / "early_entry_performance.json"
    rows = [
        {"ts": "2026-06-15T14:00:00+00:00", "ticker": "F1", "direction": "long",
         "fired": True, "price_at_entry": 100.0, "gap_band": "5-8",
         "evaluations": {"0d": {"signed_return_pct": 2.0}}},
        {"ts": "2026-06-15T14:00:00+00:00", "ticker": "C1", "direction": "long",
         "fired": False, "price_at_entry": 100.0, "gap_band": "3-5",
         "evaluations": {"0d": {"signed_return_pct": 1.0}}},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    orig_log, orig_perf = performance.EARLY_ENTRY_LOG, performance.EARLY_ENTRY_PERFORMANCE_FILE
    performance.EARLY_ENTRY_LOG = log
    performance.EARLY_ENTRY_PERFORMANCE_FILE = perf
    try:
        out = opening.compile_early_entry_stats(datetime(2026, 6, 15, 17, 0, tzinfo=ET))
    finally:
        performance.EARLY_ENTRY_LOG, performance.EARLY_ENTRY_PERFORMANCE_FILE = orig_log, orig_perf

    # net = signed − SLIPPAGE_PCT(0.5): fired 0d = 1.5, control 0d = 0.5 → edge 1.0
    check("fired count 1", out["by_fired"]["fired"]["count"] == 1)
    check("control count 1", out["by_fired"]["control"]["count"] == 1)
    check("edge 0d == 1.0", out["fired_vs_control_edge_net"]["0d"] == 1.0)
    check("by_gap_band has 5-8", "5-8" in out["by_gap_band"])
    check("perf file written", perf.exists())


if __name__ == "__main__":
    test_build()
    test_regime_suppresses_shorts()
    test_no_intraday()
    test_grading()
    test_grading_short_sign_and_unsettled()
    test_compile_edge()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
