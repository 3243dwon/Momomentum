"""Unit tests for scanner.risk — position sizing, hard stops, portfolio risk.

Pure-stdlib (no pandas / network), so they run instantly. Mirrors the check()
harness used by the other scanner tests. Run:  .venv/bin/python tests/test_risk.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import risk

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


def test_size_position_math():
    print("test_size_position (risk-based share math, both directions)")
    # equity 100k, risk 0.75% = $750 budget. entry 100, stop 95 → $5/share risk.
    # 750 / 5 = 150 shares. notional 150*100 = 15,000 (well under the 25k cap).
    out = risk.size_position(100_000, 100, 95)
    check("shares == floor(budget/dist) == 150", out["shares"] == 150)
    check("notional == 15000", out["notional"] == 15_000.0)
    check("risk_amount == shares*dist == 750", out["risk_amount"] == 750.0)
    check("pct_of_equity == 0.15", out["pct_of_equity"] == 0.15)
    check("not capped", out["capped"] is False)

    # floor() truncates fractional shares (does not round up).
    out2 = risk.size_position(100_000, 100, 93)  # dist 7 → 750/7 = 107.14 → 107
    check("shares floored (107, not 108)", out2["shares"] == 107)

    # Short trade: only |entry - stop| matters, stop above entry.
    out3 = risk.size_position(100_000, 100, 105)  # dist 5 → same 150 shares
    check("short sizing == long (abs distance)", out3["shares"] == 150)

    # custom risk_pct scales the budget linearly — but 1500 budget over $5/share
    # = 300 shares = 30k notional, which the 25% cap (25k) clamps to 250.
    out4 = risk.size_position(100_000, 100, 95, risk_pct=0.015)  # 1500 budget
    check("risk_pct=1.5% budget→300 then capped to 250", out4["shares"] == 250)
    check("risk_pct=1.5% capped flag", out4["capped"] is True)
    # Raise the cap so the larger budget actually flows through uncapped.
    out5 = risk.size_position(100_000, 100, 95, risk_pct=0.015, max_position_pct=0.5)
    check("risk_pct=1.5% uncapped → 300 shares", out5["shares"] == 300)


def test_size_position_cap():
    print("test_size_position (max_position notional cap)")
    # Tight stop: entry 100, stop 99.5 → $0.5/share. budget 750 → 1500 shares,
    # but that's 150k notional >> 25k cap → clamp to floor(25000/100) = 250.
    out = risk.size_position(100_000, 100, 99.5)
    check("capped flag True", out["capped"] is True)
    check("shares clamped to cap (250)", out["shares"] == 250)
    check("notional == cap == 25000", out["notional"] == 25_000.0)
    check("pct_of_equity == max_position_pct (0.25)", out["pct_of_equity"] == 0.25)
    # custom max_position_pct moves the ceiling.
    out2 = risk.size_position(100_000, 100, 99.5, max_position_pct=0.10)
    check("custom cap 10% → 100 shares", out2["shares"] == 100)
    check("custom cap notional 10000", out2["notional"] == 10_000.0)
    # Exactly at the cap must NOT trip the clamp (uses strict > ).
    # entry 100, stop 90 → dist 10, budget 2500 → 250 shares = 25k == cap.
    out3 = risk.size_position(100_000, 100, 90, risk_pct=0.025)
    check("notional exactly at cap not flagged", out3["capped"] is False)
    check("at-cap shares == 250", out3["shares"] == 250)


def test_size_position_edges():
    print("test_size_position (edge cases: entry==stop, zero/neg equity, non-finite)")
    # entry == stop → no stop distance → zeroed, no divide-by-zero.
    out = risk.size_position(100_000, 100, 100)
    check("entry==stop → 0 shares", out["shares"] == 0)
    check("entry==stop → notional 0", out["notional"] == 0.0)
    check("entry==stop → not capped", out["capped"] is False)

    # zero / negative equity → no budget → zeroed.
    check("zero equity → 0 shares", risk.size_position(0, 100, 95)["shares"] == 0)
    check("neg equity → 0 shares", risk.size_position(-5000, 100, 95)["shares"] == 0)
    check("zero equity pct_of_equity 0", risk.size_position(0, 100, 95)["pct_of_equity"] == 0.0)

    # non-positive / non-finite entry → zeroed.
    check("zero entry → 0 shares", risk.size_position(100_000, 0, 95)["shares"] == 0)
    check("None stop → 0 shares", risk.size_position(100_000, 100, None)["shares"] == 0)
    check("NaN equity → 0 shares",
          risk.size_position(float("nan"), 100, 95)["shares"] == 0)
    # tiny equity where budget < 1 share → floor to 0, not a crash.
    check("sub-one-share budget → 0", risk.size_position(10, 100, 95)["shares"] == 0)


def test_hard_stop():
    print("test_hard_stop (fixed %, ATR, direction, 7-8% clamp)")
    # Fixed 8% default: long stops 8% below, short 8% above.
    check("long fixed stop 8% below (92)", risk.hard_stop(100, "long") == 92.0)
    check("short fixed stop 8% above (108)", risk.hard_stop(100, "short") == 108.0)
    # Custom pct.
    check("long pct=5% → 95", risk.hard_stop(100, "long", pct=0.05) == 95.0)

    # ATR-based: 1.5 * ATR distance when ATR < the pct clamp.
    # entry 100, atr 2 → 1.5*2 = 3 < 8 → long stop 97.
    check("long ATR stop (97)", risk.hard_stop(100, "long", atr=2.0) == 97.0)
    check("short ATR stop (103)", risk.hard_stop(100, "short", atr=2.0) == 103.0)

    # ATR clamp: a wide ATR cannot exceed pct of entry (the 7-8% rule).
    # atr 10 → 1.5*10 = 15 distance, clamped to 8 → long stop 92.
    check("wide ATR clamped to 8% (92)", risk.hard_stop(100, "long", atr=10.0) == 92.0)
    check("wide ATR short clamped (108)", risk.hard_stop(100, "short", atr=10.0) == 108.0)
    # ATR exactly at clamp boundary: 1.5*atr == 8% → atr = 100*0.08/1.5.
    check("ATR at boundary (92)",
          risk.hard_stop(100, "long", atr=100 * 0.08 / 1.5) == 92.0)

    # stop is always on the protective side of entry.
    check("long stop below entry", risk.hard_stop(250, "long", atr=4) < 250)
    check("short stop above entry", risk.hard_stop(250, "short", atr=4) > 250)
    # zero/None ATR falls back to fixed pct.
    check("atr None → fixed pct (92)", risk.hard_stop(100, "long", atr=None) == 92.0)
    check("atr 0 → fixed pct (92)", risk.hard_stop(100, "long", atr=0) == 92.0)
    # degenerate entry returns unchanged (no negative stop).
    check("zero entry → 0", risk.hard_stop(0, "long") == 0.0)


def test_portfolio_risk():
    print("test_portfolio_risk (gross exposure, largest, concentration flag)")
    # Two clean positions, each 10k of a 100k book → gross 20%, largest 10%.
    positions = [
        {"ticker": "AAA", "notional": 10_000},
        {"ticker": "BBB", "notional": 10_000},
    ]
    out = risk.portfolio_risk(positions, 100_000)
    check("gross_exposure_pct 0.20", out["gross_exposure_pct"] == 0.20)
    check("largest_pct 0.10", out["largest_pct"] == 0.10)
    check("n_positions 2", out["n_positions"] == 2)
    check("not concentrated", out["concentration_flag"] is False)

    # notional derived from shares*entry when notional absent.
    out2 = risk.portfolio_risk([{"shares": 100, "entry": 50}], 100_000)
    check("notional from shares*entry (5000 → 5%)", out2["gross_exposure_pct"] == 0.05)

    # One oversized name (30% > 25% cap) trips the flag via largest_pct.
    out3 = risk.portfolio_risk([{"notional": 30_000}], 100_000)
    check("largest > 25% flagged", out3["concentration_flag"] is True)
    check("largest_pct 0.30", out3["largest_pct"] == 0.30)
    # Exactly at the 25% cap is NOT flagged (strict > ).
    out4 = risk.portfolio_risk([{"notional": 25_000}], 100_000)
    check("largest exactly 25% not flagged", out4["concentration_flag"] is False)

    # Gross-exposure flag: many small names, none over cap, but book > 1.5x.
    many = [{"notional": 20_000} for _ in range(8)]  # 160k gross on 100k → 1.6x
    out5 = risk.portfolio_risk(many, 100_000)
    check("gross 1.6x flagged", out5["concentration_flag"] is True)
    check("gross_exposure_pct 1.60", out5["gross_exposure_pct"] == 1.60)
    # short notional contributes via absolute value.
    out6 = risk.portfolio_risk([{"notional": -30_000}], 100_000)
    check("short |notional| flagged", out6["concentration_flag"] is True)


def test_portfolio_risk_edges():
    print("test_portfolio_risk (edge cases: empty book, zero equity)")
    out = risk.portfolio_risk([], 100_000)
    check("empty book gross 0", out["gross_exposure_pct"] == 0.0)
    check("empty book largest 0", out["largest_pct"] == 0.0)
    check("empty book n 0", out["n_positions"] == 0)
    check("empty book not flagged", out["concentration_flag"] is False)

    # zero equity → zeroed, unflagged, but n_positions still reported.
    z = risk.portfolio_risk([{"notional": 10_000}], 0)
    check("zero equity gross 0", z["gross_exposure_pct"] == 0.0)
    check("zero equity not flagged", z["concentration_flag"] is False)
    check("zero equity still counts positions", z["n_positions"] == 1)

    # malformed position (no notional/shares) contributes 0, doesn't crash.
    out2 = risk.portfolio_risk([{"ticker": "X"}, {"notional": 5_000}], 100_000)
    check("malformed pos → 0 contribution", out2["gross_exposure_pct"] == 0.05)
    check("malformed pos counted in n", out2["n_positions"] == 2)
    # None list is tolerated.
    check("None positions → n 0", risk.portfolio_risk(None, 100_000)["n_positions"] == 0)


def test_end_to_end():
    print("test_end_to_end (hard_stop → size_position chain)")
    # A real long: derive the stop, then size against it.
    entry = 200.0
    stop = risk.hard_stop(entry, "long", atr=3.0)  # 1.5*3=4.5 < 16 → 195.5
    check("derived stop 195.5", stop == 195.5)
    # budget 375, dist 4.5 → 83 raw shares, but 83*200=16.6k > 12.5k cap (25% of
    # 50k) → notional-capped to floor(12500/200) = 62.
    sized = risk.size_position(50_000, entry, stop)
    check("sized shares notional-capped to 62", sized["shares"] == 62)
    check("sized capped flag", sized["capped"] is True)
    check("risk_amount under budget (<= 375)", sized["risk_amount"] <= 375.0)
    # Lift the cap so the risk-budget path drives size (not the notional clamp):
    # budget 375, dist 4.5 → floor = 83, and 83*200=16.6k < 50k*0.5 cap.
    risk_sized = risk.size_position(50_000, entry, stop, max_position_pct=0.5)
    check("risk-budget path → 83 shares", risk_sized["shares"] == 83)
    check("risk-budget path not capped", risk_sized["capped"] is False)


if __name__ == "__main__":
    test_size_position_math()
    test_size_position_cap()
    test_size_position_edges()
    test_hard_stop()
    test_portfolio_risk()
    test_portfolio_risk_edges()
    test_end_to_end()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
