// Heuristic trade levels for a recommendation, derived from the price action
// already in the scan row — no extra data fetch. These are NOT advice; they're
// a structural read of recent price: where support/resistance sit, a sensible
// stop beyond the structure, and a target projected from reward:risk.
//
// Inputs used (all already on ScanRow):
//   - price        current price (entry basis)
//   - spark        last ~20 daily closes → swing low/high + volatility proxy
//   - intraday     VWAP, HOD, LOD when in a live session (refines the level)
//
// Method:
//   support (long)  = nearest meaningful level below price: the recent swing
//                     low, lifted to VWAP if VWAP sits between it and price.
//   stop            = a volatility buffer beyond that structure (so noise
//                     doesn't stop you out). Buffer = 0.5 × ATR%, where ATR%
//                     is the mean absolute close-to-close move over the spark.
//   target          = the larger of the recent swing high and a 2R projection,
//                     so a breakout name isn't capped at a stale high.
//   rr              = reward ÷ risk.
// Shorts mirror this (resistance above, stop above, target below).

import type { ScanRow, TradeLevels, RiskSizing } from './types';

export type { TradeLevels, RiskSizing };

// Reference account equity for position sizing — mirrors scanner.main
// SIZING_REFERENCE_EQUITY (~£12k ISA). A yardstick for the suggested share
// count / concentration %, NOT a live brokerage balance.
export const REFERENCE_EQUITY = 12_000;

// A deterministic plain-language trade plan built from the levels — the
// fallback so there's ALWAYS written guidance on a pick, even before the
// desk's PM writes the richer version. Plain talk, real numbers, no LLM.
export function quickPlan(l: TradeLevels): string {
  const f = (n: number) => n.toFixed(2);
  const rr = l.rr != null ? `${l.rr.toFixed(1)}R` : '—';
  if (l.side === 'long') {
    const risk = (((l.entry - l.stop) / l.entry) * 100).toFixed(1);
    const rew = (((l.target - l.entry) / l.entry) * 100).toFixed(1);
    return `Enter near $${f(l.entry)}. Stop $${f(l.stop)} (−${risk}%); first target $${f(l.target)} (+${rew}%, ${rr}). Below support at $${f(l.pivot)} the setup's done.`;
  }
  const risk = (((l.stop - l.entry) / l.entry) * 100).toFixed(1);
  const rew = (((l.entry - l.target) / l.entry) * 100).toFixed(1);
  return `Short near $${f(l.entry)}. Stop $${f(l.stop)} (+${risk}%); first target $${f(l.target)} (−${rew}%, ${rr}). Above resistance at $${f(l.pivot)} the setup's done.`;
}

function meanAbsMove(closes: number[]): number {
  if (closes.length < 2) return 0;
  let sum = 0;
  let n = 0;
  for (let i = 1; i < closes.length; i++) {
    const prev = closes[i - 1];
    if (prev > 0) {
      sum += Math.abs(closes[i] / prev - 1);
      n++;
    }
  }
  return n ? sum / n : 0; // fractional (e.g. 0.03 = 3%)
}

export function computeLevels(row: ScanRow, side: 'long' | 'short'): TradeLevels | null {
  const price = row.price;
  const spark = row.spark;
  if (price == null || price <= 0 || !spark || spark.length < 5) return null;

  // Nearer structure (last 5 bars) anchors the stop, so a far swing low on a
  // name that's already run a long way doesn't create an absurd 15%+ stop.
  // Wider window (last 10) is only used to reach for the target.
  const nearLow = Math.min(...spark.slice(-5));
  const nearHigh = Math.max(...spark.slice(-5));
  const farLow = Math.min(...spark.slice(-10));
  const farHigh = Math.max(...spark.slice(-10));

  // Volatility buffer for the stop — clamp so it's neither hair-trigger nor huge.
  const atrPct = Math.min(0.08, Math.max(0.015, meanAbsMove(spark))); // 1.5%–8%
  const buffer = price * atrPct * 0.5;
  const MAX_RISK = 0.08; // never risk more than ~8% to entry — keeps stops practical

  const vwap = row.intraday?.vwap ?? null;

  if (side === 'long') {
    // Support: nearer swing low, lifted to VWAP if VWAP is a closer floor.
    let support = nearLow;
    if (vwap != null && vwap < price && vwap > nearLow) support = vwap;
    if (support >= price) support = price * (1 - atrPct);

    let stop = support - buffer;
    const minStop = price * (1 - MAX_RISK);
    if (stop < minStop) stop = minStop; // cap stop distance at MAX_RISK
    const risk = price - stop;
    if (risk <= 0) return null;
    const target = Math.max(farHigh, price + 2 * risk);
    const rr = (target - price) / risk;
    return { side, entry: price, pivot: support, pivotLabel: 'support', stop, target, rr };
  } else {
    // Resistance: nearer swing high, pulled to VWAP if VWAP is a closer ceiling.
    let resistance = nearHigh;
    if (vwap != null && vwap > price && vwap < nearHigh) resistance = vwap;
    if (resistance <= price) resistance = price * (1 + atrPct);

    let stop = resistance + buffer;
    const maxStop = price * (1 + MAX_RISK);
    if (stop > maxStop) stop = maxStop;
    const risk = stop - price;
    if (risk <= 0) return null;
    const target = Math.min(farLow, price - 2 * risk);
    const rr = (price - target) / risk;
    return { side, entry: price, pivot: resistance, pivotLabel: 'resistance', stop, target, rr };
  }
}

// Client-side mirror of scanner/risk.py size_position(). Fixed-fractional: risk
// `equity * riskPct` over the per-share stop distance |entry − stop|, then clamp
// so one position's notional never exceeds `equity * maxPositionPct` (capped=true
// when that bites). Returns null on degenerate inputs (non-finite, entry ≤ 0,
// entry == stop) so the card simply hides sizing. Direction-agnostic — only the
// absolute entry/stop distance matters, so it's identical for longs and shorts.
export function sizePosition(
  equity: number,
  entry: number,
  stop: number,
  riskPct = 0.0075,
  maxPositionPct = 0.25
): RiskSizing | null {
  if (![equity, entry, stop].every((n) => Number.isFinite(n))) return null;
  if (equity <= 0 || entry <= 0) return null;
  const dist = Math.abs(entry - stop);
  if (dist <= 0) return null;

  let shares = Math.floor((equity * riskPct) / dist);
  const maxNotional = equity * maxPositionPct;
  let capped = false;
  if (shares * entry > maxNotional) {
    shares = Math.floor(maxNotional / entry);
    capped = true;
  }
  if (shares < 0) shares = 0;

  const notional = shares * entry;
  return {
    shares,
    notional: Math.round(notional * 100) / 100,
    risk_amount: Math.round(shares * dist * 100) / 100,
    pct_of_equity: equity ? Math.round((notional / equity) * 10000) / 10000 : 0,
    capped
  };
}
