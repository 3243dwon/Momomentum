"""Heuristic trade levels for a recommendation.

Mirror of web/src/lib/levels.ts — kept here so the desk's PM agent can write a
trade plan that references real entry/stop/target numbers, and so there's one
source of truth the frontend reads (rec["levels"]) instead of recomputing.

Output keys are camelCase to match the TS TradeLevels interface verbatim — the
dict is serialized straight into scan.json and consumed by the Svelte UI.

Method (see the TS file for the rationale):
  support (long)  = recent swing low, lifted to VWAP when VWAP is a nearer floor
  stop            = a volatility buffer (0.5 × ATR%) beyond that structure
  target          = max(recent swing high, 2R projection)
  rr              = reward ÷ risk
Shorts mirror it.  NOT investment advice.
"""
from __future__ import annotations


def _mean_abs_move(closes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0
    total = 0.0
    n = 0
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev > 0:
            total += abs(closes[i] / prev - 1)
            n += 1
    return total / n if n else 0.0


def compute_levels(row: dict, side: str) -> dict | None:
    price = row.get("price")
    spark = row.get("spark")
    if price is None or price <= 0 or not spark or len(spark) < 5:
        return None

    # Nearer structure (last 5) anchors the stop so a far swing low on a runner
    # doesn't create an absurd 15%+ stop; wider window (last 10) reaches target.
    near_low = min(spark[-5:])
    near_high = max(spark[-5:])
    far_low = min(spark[-10:])
    far_high = max(spark[-10:])

    atr_pct = min(0.08, max(0.015, _mean_abs_move(spark)))  # 1.5%–8%
    buffer = price * atr_pct * 0.5
    max_risk = 0.08  # never risk more than ~8% to entry — keeps stops practical
    vwap = (row.get("intraday") or {}).get("vwap")

    if side == "long":
        support = near_low
        if vwap is not None and vwap < price and vwap > near_low:
            support = vwap
        if support >= price:
            support = price * (1 - atr_pct)
        stop = support - buffer
        min_stop = price * (1 - max_risk)
        if stop < min_stop:
            stop = min_stop
        risk = price - stop
        if risk <= 0:
            return None
        target = max(far_high, price + 2 * risk)
        rr = (target - price) / risk
        pivot, label = support, "support"
    else:
        resistance = near_high
        if vwap is not None and vwap > price and vwap < near_high:
            resistance = vwap
        if resistance <= price:
            resistance = price * (1 + atr_pct)
        stop = resistance + buffer
        max_stop = price * (1 + max_risk)
        if stop > max_stop:
            stop = max_stop
        risk = stop - price
        if risk <= 0:
            return None
        target = min(far_low, price - 2 * risk)
        rr = (price - target) / risk
        pivot, label = resistance, "resistance"

    return {
        "side": side,
        "entry": round(float(price), 2),
        "pivot": round(float(pivot), 2),
        "pivotLabel": label,
        "stop": round(float(stop), 2),
        "target": round(float(target), 2),
        "rr": round(float(rr), 2),
    }


def attach_levels(recommendations: dict, rows: list[dict]) -> None:
    """Set rec['levels'] on every pick, in place. Deterministic, no LLM."""
    by_ticker = {r["ticker"]: r for r in rows}
    for direction in ("longs", "shorts"):
        for rec in recommendations.get(direction, []):
            row = by_ticker.get(rec.get("ticker"))
            if not row:
                continue
            lv = compute_levels(row, rec.get("direction", "long"))
            if lv:
                rec["levels"] = lv
