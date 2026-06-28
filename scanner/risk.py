"""Position sizing, hard stops and portfolio-risk checks.

Pure stdlib (no pandas/numpy, no network) so it unit-tests instantly and can be
called from any tier. This is the size-and-survive layer that sits beneath the
recommendation: scanner.recommend / levels.py say WHAT to trade and at what
entry/stop, this module says HOW MUCH and refuses to let one name or the whole
book carry too much risk.

Three deterministic primitives, all frozen by the integration contract:
  * size_position — risk-based share count, fixed-fractional with a notional cap;
  * hard_stop     — the protective stop price (ATR buffer or fixed %), enforcing
                    the same 7-8% max-loss rule as levels.py;
  * portfolio_risk — gross exposure / concentration read across open positions.

Constants live here (no config.py edit): the risk budget per trade, the single
max-position cap and the default stop width. NOT investment advice.
"""
from __future__ import annotations

from math import floor, isfinite

# Risk budget for a single trade, as a fraction of account equity. 0.75% is the
# conservative end of the classic 0.5-1% fixed-fractional rule — small enough
# that a string of stop-outs doesn't dent the account, big enough to matter.
RISK_PCT = 0.0075
# Hard ceiling on any one position's notional, as a fraction of equity. Caps
# concentration even when a tight stop would otherwise justify a huge size.
MAX_POSITION_PCT = 0.25
# Default protective-stop width when no ATR is supplied, as a fraction of entry.
# 8% matches levels.py's max_risk — beyond this a stop stops being protective.
STOP_PCT = 0.08
# Multiplier on ATR for a volatility-scaled stop. 1.5× ATR is a common swing
# buffer; the result is still clamped to STOP_PCT so it never exceeds the rule.
ATR_STOP_MULT = 1.5
# Gross-exposure ceiling for the whole book (sum of |notional| / equity). Above
# 1.5x the account is meaningfully leveraged and the book is flagged.
MAX_GROSS_EXPOSURE = 1.5


def _finite(x) -> bool:
    """True for a real, finite number (rejects None, NaN, inf)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and isfinite(x)


def size_position(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float = RISK_PCT,
    max_position_pct: float = MAX_POSITION_PCT,
) -> dict:
    """Fixed-fractional share count for one trade, capped by notional.

    Risk `equity * risk_pct` over the per-share stop distance |entry - stop|,
    then clamp so the position's notional never exceeds `equity * max_position_pct`
    (capped=True when that clamp bites). Returns zeroed sizing (never raises) when
    inputs are degenerate — non-finite, non-positive equity/entry, or entry==stop
    (no stop distance, so risk-per-share is undefined).

    Direction-agnostic: pass entry and stop in price terms and only the absolute
    distance matters, so it works identically for longs and shorts.
    """
    zero = {"shares": 0, "notional": 0.0, "risk_amount": 0.0,
            "pct_of_equity": 0.0, "capped": False}
    if not (_finite(equity) and _finite(entry) and _finite(stop)):
        return zero
    if equity <= 0 or entry <= 0:
        return zero

    stop_distance = abs(entry - stop)
    if stop_distance <= 0:  # entry == stop → risk-per-share undefined
        return zero

    risk_budget = equity * risk_pct
    shares = floor(risk_budget / stop_distance)

    # Notional cap: a tight stop can imply a position larger than we'll allow one
    # name to be, so clamp share count down to the cap and flag it.
    max_notional = equity * max_position_pct
    capped = False
    if shares * entry > max_notional:
        shares = floor(max_notional / entry)
        capped = True

    if shares < 0:
        shares = 0
    notional = shares * entry
    return {
        "shares": int(shares),
        "notional": round(float(notional), 2),
        "risk_amount": round(float(shares * stop_distance), 2),
        "pct_of_equity": round(notional / equity, 4) if equity else 0.0,
        "capped": capped,
    }


def hard_stop(
    entry: float,
    direction: str,
    atr: float | None = None,
    pct: float = STOP_PCT,
) -> float:
    """Protective stop price for a trade.

    ATR-based when `atr` is supplied (entry -/+ ATR_STOP_MULT * atr), else a flat
    `pct` of entry. Either way the loss to the stop is clamped to `pct` of entry,
    enforcing the 7-8% max-loss rule (a wide-ATR name can't dictate a 20% stop).
    `direction` uses rec["direction"] vocabulary: "long" stops below entry, any
    other value ("short") stops above. Returns entry unchanged for a degenerate
    (non-finite / non-positive) entry.
    """
    if not _finite(entry) or entry <= 0:
        return float(entry) if _finite(entry) else 0.0

    long = direction == "long"
    if _finite(atr) and atr > 0:
        distance = ATR_STOP_MULT * atr
    else:
        distance = entry * pct

    # Clamp the loss to pct of entry so the stop stays protective.
    max_distance = entry * pct
    if distance > max_distance:
        distance = max_distance

    stop = entry - distance if long else entry + distance
    return round(float(stop), 2)


def portfolio_risk(open_positions: list[dict], equity: float) -> dict:
    """Gross exposure and concentration across open positions.

    Each position contributes a notional, read as `notional` if present else
    `shares * entry`. Returns gross-exposure-% (sum |notional| / equity),
    largest single-position-% and a concentration flag raised when one name
    exceeds MAX_POSITION_PCT or the book's gross exposure exceeds MAX_GROSS_EXPOSURE.
    Degenerate equity (non-finite / non-positive) yields zeroed, unflagged risk.
    """
    n = len(open_positions or [])
    if not (_finite(equity) and equity > 0):
        return {"gross_exposure_pct": 0.0, "largest_pct": 0.0,
                "n_positions": n, "concentration_flag": False}

    gross = 0.0
    largest = 0.0
    for pos in open_positions or []:
        notional = pos.get("notional")
        if not _finite(notional):
            shares = pos.get("shares")
            entry = pos.get("entry")
            notional = (shares * entry) if (_finite(shares) and _finite(entry)) else 0.0
        notional = abs(float(notional))
        gross += notional
        if notional > largest:
            largest = notional

    gross_pct = gross / equity
    largest_pct = largest / equity
    flag = largest_pct > MAX_POSITION_PCT or gross_pct > MAX_GROSS_EXPOSURE
    return {
        "gross_exposure_pct": round(gross_pct, 4),
        "largest_pct": round(largest_pct, 4),
        "n_positions": n,
        "concentration_flag": bool(flag),
    }
