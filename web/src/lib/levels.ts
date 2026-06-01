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

import type { ScanRow } from './types';

export interface TradeLevels {
  side: 'long' | 'short';
  entry: number;
  /** structural pivot — support for longs, resistance for shorts */
  pivot: number;
  pivotLabel: 'support' | 'resistance';
  stop: number;
  target: number;
  /** reward:risk multiple, or null if risk is degenerate */
  rr: number | null;
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

  const recent = spark.slice(-10);
  const swingLow = Math.min(...recent);
  const swingHigh = Math.max(...recent);

  // Volatility buffer for the stop — clamp so it's neither hair-trigger nor huge.
  const atrPct = Math.min(0.08, Math.max(0.015, meanAbsMove(spark))); // 1.5%–8%
  const buffer = price * atrPct * 0.5;

  const vwap = row.intraday?.vwap ?? null;

  if (side === 'long') {
    // Support: recent swing low, lifted to VWAP if VWAP is below price but
    // above the swing low (a nearer, more relevant floor).
    let support = swingLow;
    if (vwap != null && vwap < price && vwap > swingLow) support = vwap;
    if (support >= price) support = price * (1 - atrPct); // degenerate: price at/below lows

    const stop = support - buffer;
    const risk = price - stop;
    if (risk <= 0) return null;
    const target = Math.max(swingHigh, price + 2 * risk);
    const rr = (target - price) / risk;
    return { side, entry: price, pivot: support, pivotLabel: 'support', stop, target, rr };
  } else {
    // Resistance: recent swing high, pulled to VWAP if VWAP is above price but
    // below the swing high.
    let resistance = swingHigh;
    if (vwap != null && vwap > price && vwap < swingHigh) resistance = vwap;
    if (resistance <= price) resistance = price * (1 + atrPct);

    const stop = resistance + buffer;
    const risk = stop - price;
    if (risk <= 0) return null;
    const target = Math.min(swingLow, price - 2 * risk);
    const rr = (price - target) / risk;
    return { side, entry: price, pivot: resistance, pivotLabel: 'resistance', stop, target, rr };
  }
}
