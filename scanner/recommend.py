"""Momentum-quality recommendation scoring.

Ranks the enriched scan rows into long and short pick lists. Rewards
confirmed momentum (volume, MACD, VWAP, RSI trend zone) and news-backed
catalysts; the scanner's "stretched" caution_level disqualifies a row as a
late entry. The web Recommended section renders the picks computed here,
and scanner.performance tracks their 1/3/5-day outcomes.

Single source of truth — keep web/src/lib/types.ts Recommendation in sync
with the dict shape emitted by compute().
"""
from __future__ import annotations

MIN_SCORE = 5
MAX_PER_SIDE = 6


def _score_row(row: dict, direction: str) -> dict | None:
    """Score one row for one direction. Returns a recommendation dict, or
    None if the row doesn't clear MIN_SCORE / isn't a valid entry."""
    p1 = row.get("pct_1d")
    if p1 is None or p1 == 0:
        return None

    # A favorable move is positive when price action agrees with the trade.
    long = direction == "long"
    fav1 = p1 if long else -p1
    if fav1 <= 0:
        return None

    # "stretched" means the move is already exhausted — never a fresh entry.
    if row.get("caution_level") == "stretched":
        return None

    score = 0
    reasons: list[str] = []
    cautions: list[str] = []
    move_sign = "+" if long else "-"

    # Day move: enough to signal momentum, not so far it's a chase.
    if 1.5 <= fav1 < 5:
        score += 2
        reasons.append(f"{move_sign}{fav1:.1f}% today")
    elif (0 < fav1 < 1.5) or (5 <= fav1 < 9):
        score += 1
        reasons.append(f"{move_sign}{fav1:.1f}% today")

    # 5-day trend in the same direction (but not already parabolic).
    p5 = row.get("pct_5d")
    if p5 is not None:
        fav5 = p5 if long else -p5
        if 1 <= fav5 < 18:
            score += 1
            trend = "uptrend" if long else "downtrend"
            reasons.append(f"5d {trend} {'+' if p5 > 0 else ''}{p5:.0f}%")

    # Volume confirmation.
    rv = row.get("rel_volume")
    if rv is not None:
        if rv >= 2:
            score += 2
            reasons.append(f"{rv:.1f}x volume")
        elif rv >= 1.5:
            score += 1
            reasons.append(f"{rv:.1f}x volume")

    # MACD: a fresh cross is the strongest trend signal; histogram is weaker.
    want_cross = "bullish" if long else "bearish"
    macd_hist = row.get("macd_hist")
    if row.get("macd_cross") == want_cross:
        score += 2
        reasons.append(f"MACD {want_cross} cross")
    elif macd_hist is not None and (macd_hist > 0 if long else macd_hist < 0):
        score += 1
        reasons.append(f"MACD {'positive' if long else 'negative'}")

    # Intraday strength holding on the right side of VWAP.
    above_vwap = (row.get("intraday") or {}).get("above_vwap")
    if long and above_vwap is True:
        score += 1
        reasons.append("above VWAP")
    elif not long and above_vwap is False:
        score += 1
        reasons.append("below VWAP")

    # RSI: reward the trend zone, penalize the exhausted extreme.
    rsi = row.get("rsi_14")
    if rsi is not None:
        if long:
            if 55 <= rsi <= 72:
                score += 1
                reasons.append(f"RSI {rsi:.0f} trending")
            elif rsi > 80:
                score -= 2
                cautions.append(f"RSI {rsi:.0f} overbought")
            elif rsi > 75:
                score -= 1
                cautions.append(f"RSI {rsi:.0f} elevated")
        else:
            if 28 <= rsi <= 45:
                score += 1
                reasons.append(f"RSI {rsi:.0f} weak")
            elif rsi < 20:
                score -= 2
                cautions.append(f"RSI {rsi:.0f} oversold")
            elif rsi < 25:
                score -= 1
                cautions.append(f"RSI {rsi:.0f} washed out")

    # News catalyst — a synthesis-confirmed move is the highest-quality signal.
    syn = row.get("synthesis")
    if syn:
        verdict = syn.get("verdict")
        if verdict == "news_explains_move":
            high = syn.get("confidence") == "high"
            score += 3 if high else 2
            reasons.append("news-confirmed catalyst" if high else "news-driven move")
        elif verdict == "partial_explanation":
            score += 1
            reasons.append("partly news-driven")
        elif verdict == "move_unexplained_by_news":
            score -= 1
            cautions.append("unexplained move")
    else:
        news_count = row.get("news_count") or 0
        if news_count > 0:
            score += 1
            noun = "headline" if news_count == 1 else "headlines"
            reasons.append(f"{news_count} fresh {noun}")

    # An "extended" move is a worse entry, but not disqualifying like "stretched".
    if row.get("caution_level") == "caution":
        score -= 2
        cautions.append("extended")

    if score < MIN_SCORE:
        return None
    # Horizon: news-backed picks have a thesis to hold beyond the next tick;
    # pure-technical picks are intraday/days price-action trades.
    catalyst_backed = bool(
        syn and syn.get("verdict") in ("news_explains_move", "partial_explanation")
    )
    return {
        "ticker": row["ticker"],
        "direction": direction,
        "score": score,
        "horizon": "long" if catalyst_backed else "short",
        "reasons": reasons,
        "cautions": cautions,
    }


# Minimum score required for shorts to survive a bull regime. Set high so
# only the most extreme technical setups make it through when SPY > 50d MA —
# perf data showed short_hi averaging -3.57% over 5 days in this regime, so
# the default behavior is to suppress shorts entirely.
SHORT_BULL_REGIME_MIN_SCORE = 9


def compute(rows: list[dict], regime: dict | None = None) -> dict:
    """Score every row for both directions; return the top picks per side.

    Each recommendation is {ticker, direction, score, reasons, cautions} —
    the web app joins it back to the full scan row by ticker for display.

    `regime` (optional) is the output of scanner.regime.compute(). When SPY
    is above its 50-day MA we suppress shorts (or filter to extreme scores
    only) because shorting strength in a bull tape historically loses money
    — verified against data/recommendation_performance.json.
    """
    rel_vol = {r["ticker"]: (r.get("rel_volume") or 0) for r in rows}
    longs: list[dict] = []
    shorts: list[dict] = []
    for row in rows:
        rec = _score_row(row, "long")
        if rec:
            longs.append(rec)
        rec = _score_row(row, "short")
        if rec:
            shorts.append(rec)

    # Best score first; ties broken by relative volume (conviction).
    def sort_key(rec: dict) -> tuple[int, float]:
        return (-rec["score"], -rel_vol.get(rec["ticker"], 0))

    longs.sort(key=sort_key)
    shorts.sort(key=sort_key)

    # --- Bull-regime short suppression --------------------------------------
    # Empty regime = no data → skip the gate, behave as before (don't punish
    # the user for an Alpaca outage). spy_above_50d explicitly False = bear/
    # choppy regime → keep shorts. True = bull tape → suppress.
    if regime and regime.get("spy_above_50d") is True:
        before = len(shorts)
        shorts = [s for s in shorts if s["score"] >= SHORT_BULL_REGIME_MIN_SCORE]
        if before != len(shorts):
            import logging
            logging.getLogger(__name__).info(
                "Bull regime (SPY > 50d): shorts %d → %d (kept score >= %d)",
                before, len(shorts), SHORT_BULL_REGIME_MIN_SCORE,
            )

    return {"longs": longs[:MAX_PER_SIDE], "shorts": shorts[:MAX_PER_SIDE]}
