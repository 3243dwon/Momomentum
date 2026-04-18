"""Late-entry risk scoring for movers.

A top-20 mover showing on your screen likely has 15-30 minutes of delay
by the time you see it. The question worth answering: is there still room
to run, or is this already played out?

We compute a staleness score from signals of move exhaustion:
- RSI overextended (>75 overbought / <25 oversold)
- Multi-day move already fat (5d |%chg| > 10-20%)
- Intraday giveback from HOD (price well below day's high)
- Far above/below VWAP (stretched)
- At or near 20-day high with no overhead resistance

Buckets:
- 'none'       — normal, no warning
- 'caution'    — yellow pill, be mindful
- 'stretched'  — red pill, late entry high risk

Purely deterministic (no LLM) so it runs on every row without cost.
"""
from __future__ import annotations


def compute(row: dict) -> tuple[str, list[str]]:
    """Return (level, reasons). Level in ('none', 'caution', 'stretched')."""
    pct_1d = row.get("pct_1d") or 0
    pct_5d = row.get("pct_5d") or 0
    rsi = row.get("rsi_14")
    intraday = row.get("intraday") or {}
    spark = row.get("spark") or []
    price = row.get("price")

    score = 0
    reasons: list[str] = []

    # --- RSI extremes ---
    if rsi is not None:
        if rsi > 75:
            score += 2
            reasons.append(f"RSI {rsi:.0f} overbought")
        elif rsi > 70:
            score += 1
            reasons.append(f"RSI {rsi:.0f} elevated")
        elif rsi < 25:
            score += 2
            reasons.append(f"RSI {rsi:.0f} oversold")
        elif rsi < 30:
            score += 1
            reasons.append(f"RSI {rsi:.0f} weak")

    # --- Multi-day move already fat ---
    if abs(pct_5d) >= 20:
        score += 2
        reasons.append(f"{pct_5d:+.0f}% over 5d")
    elif abs(pct_5d) >= 10:
        score += 1
        reasons.append(f"{pct_5d:+.0f}% over 5d")

    # --- Intraday giveback from HOD (only meaningful if move is up) ---
    hod = intraday.get("hod")
    last = intraday.get("last")
    if hod and last and pct_1d > 0 and hod > 0:
        giveback_pct = (hod - last) / hod * 100
        if giveback_pct >= 5:
            score += 2
            reasons.append(f"{giveback_pct:.1f}% off HOD")
        elif giveback_pct >= 3:
            score += 1
            reasons.append(f"{giveback_pct:.1f}% off HOD")

    # --- Far above/below VWAP (stretched) ---
    vwap = intraday.get("vwap")
    if vwap and last and vwap > 0:
        dist_pct = (last - vwap) / vwap * 100
        if abs(dist_pct) >= 4:
            score += 1
            reasons.append(f"{dist_pct:+.1f}% vs VWAP")

    # --- At 20-day high / low (no nearby resistance / support) ---
    if spark and len(spark) >= 10 and price:
        high_20 = max(spark)
        low_20 = min(spark)
        if high_20 > 0 and price >= high_20 * 0.985 and pct_1d > 0:
            score += 1
            reasons.append("at 20d high")
        elif low_20 > 0 and price <= low_20 * 1.015 and pct_1d < 0:
            score += 1
            reasons.append("at 20d low")

    if score >= 5:
        return "stretched", reasons
    if score >= 3:
        return "caution", reasons
    return "none", reasons
