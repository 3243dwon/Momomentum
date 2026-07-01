"""Unit tests for Contract G — Gating: prune alert streams + dollar-volume floor.

Pure stdlib (pytest is NOT installed in .venv). All offline: build_alerts only
touches scanner.config, and we monkeypatch it. Run:
    .venv/bin/python tests/test_gating.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import config, universe
from scanner.alerts import rules
from scanner.windows import Window

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


def _row(ticker, pct, *, rel_vol=1.0, vol=1_000_000, flags=None, caution=None):
    r = {
        "ticker": ticker,
        "pct_1d": pct,
        "rel_volume": rel_vol,
        "volume": vol,
        "flags": flags or [],
    }
    if caution:
        r["caution_level"] = caution
    return r


def _types(alerts):
    return [a.get("type") for a in alerts]


def _of_type(alerts, t):
    return [a for a in alerts if a.get("type") == t]


# --------------------------------------------------------------------------
# 1. universe.passes_liquidity_floor
# --------------------------------------------------------------------------
def test_liquidity_floor():
    print("test_liquidity_floor")
    with mock.patch.object(config, "MIN_DOLLAR_VOLUME", 5_000_000.0):
        # price * vol relative to the $5M floor
        check("above floor -> True", universe.passes_liquidity_floor(10.0, 600_000))   # 6M
        check("below floor -> False", not universe.passes_liquidity_floor(10.0, 400_000))  # 4M
        check("exactly at floor -> True (>=)", universe.passes_liquidity_floor(10.0, 500_000))  # 5M
        # fail-open on missing/garbage inputs
        check("None price -> True", universe.passes_liquidity_floor(None, 600_000))
        check("None volume -> True", universe.passes_liquidity_floor(10.0, None))
        check("NaN price -> True", universe.passes_liquidity_floor(float("nan"), 600_000))
        check("NaN volume -> True", universe.passes_liquidity_floor(10.0, float("nan")))
        # explicit arg overrides config default
        check("explicit floor overrides (below)",
              not universe.passes_liquidity_floor(10.0, 600_000, min_dollar_volume=10_000_000))  # 6M < 10M
        check("explicit floor overrides (above)",
              universe.passes_liquidity_floor(10.0, 600_000, min_dollar_volume=1_000_000))  # 6M >= 1M
    # 0 disables regardless of config
    check("min_dollar_volume=0 -> always True",
          universe.passes_liquidity_floor(0.01, 1, min_dollar_volume=0))
    with mock.patch.object(config, "MIN_DOLLAR_VOLUME", 0.0):
        check("config floor 0 -> always True",
              universe.passes_liquidity_floor(0.01, 1))


# --------------------------------------------------------------------------
# 2. Serenity throttle in build_alerts
# --------------------------------------------------------------------------
def _serenity(ticker, pct):
    return {"ticker": ticker, "pct_1d": pct, "stance": "bull", "summary": "x", "url": None}


def test_serenity_throttle():
    print("test_serenity_throttle (kill-switch, move floor, per-type cap)")
    base = [_serenity("AAA", 6.0)]
    # kill-switch
    with mock.patch.object(config, "SERENITY_MATCH_ENABLED", False):
        alerts, _ = rules.build_alerts([], {}, {}, [], Window.RTH, serenity_matches=base)
        check("disabled -> zero serenity_match", not _of_type(alerts, "serenity_match"))

    with mock.patch.object(config, "SERENITY_MATCH_ENABLED", True), \
         mock.patch.object(config, "SERENITY_MATCH_MIN_MOVE_PCT", 5.0), \
         mock.patch.object(config, "SERENITY_MATCH_MAX_PER_SCAN", 2):
        matches = [_serenity("AAA", 4.0), _serenity("BBB", 6.0), _serenity("CCC", None)]
        alerts, _ = rules.build_alerts([], {}, {}, [], Window.RTH, serenity_matches=matches)
        sm = _of_type(alerts, "serenity_match")
        tickers = {a["ticker"] for a in sm}
        check("pct=4.0 < 5.0 -> dropped", "AAA" not in tickers)
        check("pct=6.0 -> kept", "BBB" in tickers)
        check("pct=None -> dropped", "CCC" not in tickers)

    # per-type cap
    with mock.patch.object(config, "SERENITY_MATCH_ENABLED", True), \
         mock.patch.object(config, "SERENITY_MATCH_MIN_MOVE_PCT", 5.0), \
         mock.patch.object(config, "SERENITY_MATCH_MAX_PER_SCAN", 1):
        matches = [_serenity("AAA", 6.0), _serenity("BBB", 9.0)]
        alerts, _ = rules.build_alerts([], {}, {}, [], Window.RTH, serenity_matches=matches)
        sm = _of_type(alerts, "serenity_match")
        check("cap=1 with 2 qualifying -> 1 serenity_match", len(sm) == 1)
        check("cap keeps strongest (BBB)", sm and sm[0]["ticker"] == "BBB")


# --------------------------------------------------------------------------
# 3. KEEP-list regression: catalyst / ripple / macro never capped by gating
# --------------------------------------------------------------------------
def test_keep_list_regression():
    print("test_keep_list_regression (catalyst/ripple/macro untouched)")
    rows = [
        _row("CAT", 6.0, rel_vol=3.5, flags=["big_move", "unusual_volume"]),
        _row("CAT2", 7.0, rel_vol=3.5, flags=["big_move", "unusual_volume"]),
    ]
    syntheses = {
        "CAT": {"verdict": "news_explains_move", "confidence": "high", "summary": "deal"},
        "CAT2": {"verdict": "news_explains_move", "confidence": "high", "summary": "beat"},
    }
    macro = [{"event_summary": "CPI cools", "beneficiaries": [{"ticker": "XLF"}],
              "losers": [], "dedup_group": "cpi"}]
    ripples = [
        {"ticker": "RIP1", "priced_in": "no", "confidence": "high", "direction": "bullish",
         "trigger_ticker": "NVDA", "rationale": "supplier", "horizon": "1-3d", "pct_1d": 0.5},
        {"ticker": "RIP2", "priced_in": "no", "confidence": "medium", "direction": "bullish",
         "trigger_ticker": "NVDA", "rationale": "supplier", "horizon": "1-3d", "pct_1d": 0.5},
    ]
    with mock.patch.object(config, "SERENITY_MATCH_MAX_PER_SCAN", 0), \
         mock.patch.object(config, "SERENITY_MATCH_ENABLED", True):
        alerts, _ = rules.build_alerts(rows, {}, syntheses, macro, Window.RTH,
                                       ripple_predictions=ripples)
        ts = _types(alerts)
        check("both catalysts survive (per-type caps don't touch them)",
              len(_of_type(alerts, "catalyst")) == 2)
        check("both ripples survive", len(_of_type(alerts, "ripple")) == 2)
        check("macro survives", any(t.startswith("macro:") for t in ts))


# --------------------------------------------------------------------------
# 4. Delta guard
# --------------------------------------------------------------------------
def test_delta_guard():
    print("test_delta_guard")
    check("DELTA_ALERTS_ENABLED defaults False", config.DELTA_ALERTS_ENABLED is False)
    rows = [_row("AAA", 8.0, rel_vol=4.0, flags=["big_move", "unusual_volume"])]
    alerts, _ = rules.build_alerts(rows, {"foo": "bar"}, {}, [], Window.RTH)
    check("no delta_* alert ever emitted",
          not any((a.get("type") or "").startswith("delta_") for a in alerts))


# --------------------------------------------------------------------------
# 5. Throttle interaction: record_dispatched still pops _signal_abs
# --------------------------------------------------------------------------
def test_record_dispatched_backcompat():
    print("test_record_dispatched_backcompat")
    with mock.patch.object(config, "SERENITY_MATCH_ENABLED", True), \
         mock.patch.object(config, "SERENITY_MATCH_MIN_MOVE_PCT", 5.0), \
         mock.patch.object(config, "SERENITY_MATCH_MAX_PER_SCAN", 2):
        matches = [_serenity("AAA", 6.0), _serenity("BBB", 9.0)]
        alerts, throttle = rules.build_alerts([], {}, {}, [], Window.RTH, serenity_matches=matches)
        sm = _of_type(alerts, "serenity_match")
        check("survivor still carries _signal_abs", bool(sm) and "_signal_abs" in sm[0])
        # record_dispatched pops _signal_abs and commits — patch commit to avoid disk I/O
        with mock.patch.object(throttle, "commit", lambda: None):
            try:
                rules.record_dispatched(alerts, throttle)
                ok = all("_signal_abs" not in a for a in alerts)
            except KeyError:
                ok = False
        check("record_dispatched pops _signal_abs without KeyError", ok)


def main():
    test_liquidity_floor()
    test_serenity_throttle()
    test_keep_list_regression()
    test_delta_guard()
    test_record_dispatched_backcompat()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
