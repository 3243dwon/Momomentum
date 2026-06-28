"""Momentum-quality recommendation scoring.

Ranks the enriched scan rows into long and short pick lists. Rewards
confirmed momentum (volume, MACD, VWAP, RSI trend zone) and news-backed
catalysts; the scanner's "stretched" caution_level disqualifies a row as a
late entry. The web Recommended section renders the picks computed here,
and scanner.performance tracks their 1/3/5-day outcomes.

Single source of truth — keep web/src/lib/types.ts Recommendation in sync
with the dict shape emitted by compute() (now incl. entry_style, base_ready,
horizon_days; horizon stays the legacy 'long'/'short' hold-bucket string).
"""
from __future__ import annotations

MIN_SCORE = 5
MAX_PER_SIDE = 6

# --- Catalyst durability + drift (consumes row["synthesis"], contract A/B) ----
# durability_weight is the catalyst's drift potential (0=soft … 3=structural).
# DURABILITY_POINTS scales the news-verdict score by that weight: structural=4
# is intentionally >= the old flat +3 so existing high-conviction picks are not
# demoted below MIN_SCORE the day this ships (back-compat asserted in tests).
DURABILITY_POINTS = {0: 1, 1: 2, 2: 3, 3: 4}  # soft/surprise/guidance/structural
# Derive the weight when only the durability label is present (no weight key).
_DURABILITY_WEIGHT = {"soft": 0, "surprise": 1, "guidance": 2, "structural": 3}
# priced_in gate: reward tape that hasn't discounted the catalyst (or is
# positioned the wrong way), penalize a fully-discounted move. A soft gate —
# "yes" at -3 can drop a borderline pick below MIN_SCORE, but a strong technical
# setup can still survive (not a hard reject).
PRICED_IN_DELTA = {"no": 1, "contradicted": 2, "partial": 0, "yes": -3}
# Suggested hold in TRADING days, scaled by drift potential. Max is 21 == the
# longest graded horizon in performance.HORIZONS, so we never suggest a hold the
# grader can't score. Distinct from the legacy string rec["horizon"].
HORIZON_DAYS = {0: 3, 1: 5, 2: 10, 3: 21}  # soft/surprise/guidance/structural
DEFAULT_HORIZON_DAYS = 3  # no-catalyst technical picks inherit the soft horizon


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
    # Durability scales the points (a definitive contract drifts longer than a
    # sentiment note), and priced_in gates them (a fully-discounted move fades).
    # Tolerate the catalyst fields being absent or malformed: synthesize.py only
    # ships verdict/confidence today; durability/durability_weight/priced_in
    # arrive later (contract A/B). Everything reads through isinstance/.get() so
    # a non-dict synthesis never raises.
    syn = row.get("synthesis")
    is_syn = isinstance(syn, dict)
    dw = 0
    if is_syn:
        verdict = syn.get("verdict")
        dw = syn.get("durability_weight")
        if dw is None:
            dw = _DURABILITY_WEIGHT.get(syn.get("durability"))
        # Clamp to the contract's 0..3 domain — a missing or out-of-range weight
        # (the catalyst unit owns that field) falls back to soft so the points /
        # horizon lookups below can never raise on a malformed synthesis.
        if dw not in DURABILITY_POINTS:
            dw = 0
        if verdict in ("news_explains_move", "partial_explanation"):
            pts = DURABILITY_POINTS[dw]
            if syn.get("confidence") != "high":
                pts = max(pts - 1, 1)
            if verdict == "partial_explanation":
                pts = max(pts - 1, 1)
            score += pts
            tier = next((k for k, v in _DURABILITY_WEIGHT.items() if v == dw), "soft")
            reasons.append(f"{tier} catalyst" if verdict == "news_explains_move"
                           else f"partly news-driven ({tier})")
        elif verdict == "move_unexplained_by_news":
            score -= 1
            cautions.append("unexplained move")

        # priced_in gate — reward un-discounted / contradicted tape, fade "yes".
        pi = syn.get("priced_in")
        score += PRICED_IN_DELTA.get(pi, 0)
        if pi == "yes":
            cautions.append("catalyst priced in")
        elif pi == "contradicted":
            reasons.append("tape positioned wrong way")
        elif pi == "no":
            reasons.append("catalyst not priced in")
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
        is_syn and syn.get("verdict") in ("news_explains_move", "partial_explanation")
    )
    # Drift-scaled hold in trading days (soft 3 … structural 21). No-catalyst
    # technical picks inherit the soft horizon rather than null.
    horizon_days = HORIZON_DAYS.get(dw, DEFAULT_HORIZON_DAYS) if catalyst_backed \
        else DEFAULT_HORIZON_DAYS
    # base_ready: a catalyst-backed name that hasn't gone vertical is a "buy the
    # base" setup. caution_level is the only consolidation proxy on the row
    # (stretched/caution/absent), so this is a v1 fidelity gap — true range-
    # contraction-after-the-event detection isn't derivable from current fields.
    base_ready = catalyst_backed and row.get("caution_level") != "stretched"
    entry_style = "base" if base_ready else "spike"
    return {
        "ticker": row["ticker"],
        "direction": direction,
        "score": score,
        "horizon": "long" if catalyst_backed else "short",
        "reasons": reasons,
        "cautions": cautions,
        "entry_style": entry_style,
        "base_ready": base_ready,
        "horizon_days": horizon_days,
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
