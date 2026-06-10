// Trust grading — puts the track record next to the calls instead of
// quarantining it on a stats page. Thresholds: a signal class is only
// "trusted" with a real sample (n>=30) and >=55% hit; "noise" is <45% on a
// real sample. Everything else is unproven — including brand-new signals.
import type {
  PerformanceData,
  RecommendationPerformance,
  AlertTypeStats,
  HorizonStats
} from './types';

export type TrustGrade = 'trusted' | 'unproven' | 'noise';

export interface SignalTrust {
  grade: TrustGrade;
  hitRate: number | null; // 0-100
  n: number; // evaluated at this horizon
  fired: number; // total logged
  avgReturn: number | null; // signed pct, in call direction
  label: string; // one human line, render-ready
}

const MIN_N = 30;

function horizonStats(stats: AlertTypeStats | undefined, horizon: '1d' | '3d' | '5d'): HorizonStats | null {
  return stats?.horizons?.[horizon] ?? null;
}

function grade(hit: number | null, n: number): TrustGrade {
  if (hit == null || n < MIN_N) return 'unproven';
  if (hit >= 0.55) return 'trusted';
  if (hit < 0.45) return 'noise';
  return 'unproven';
}

function describe(g: TrustGrade, hitPct: number | null, n: number, avg: number | null): string {
  if (hitPct == null || n === 0) return 'no outcomes yet — too new to grade';
  const core = `${Math.round(hitPct)}% hit · ${avg != null ? `${avg > 0 ? '+' : ''}${avg.toFixed(2)}% avg` : '–'} · n=${n}`;
  if (g === 'noise') return `historically noise — ${core}`;
  if (g === 'trusted') return core;
  return `${core} — unproven`;
}

/** Track record for an alert/signal class (catalyst, serenity_match, ripple…). */
export function signalTrust(
  perf: PerformanceData | null | undefined,
  type: string,
  horizon: '1d' | '3d' | '5d' = '1d'
): SignalTrust | null {
  const stats = perf?.per_type?.[type];
  if (!stats) return null;
  const h = horizonStats(stats, horizon);
  const hit = h?.hit_rate ?? null;
  const n = h?.evaluated ?? 0;
  const g = grade(hit, n);
  const hitPct = hit != null ? hit * 100 : null;
  return {
    grade: g,
    hitRate: hitPct,
    n,
    fired: stats.count,
    avgReturn: h?.avg_return_pct ?? null,
    label: describe(g, hitPct, n, h?.avg_return_pct ?? null)
  };
}

/** Track record for a pick's score band (long_hi / long_lo / short_hi / short_lo). */
export function bandTrust(
  recPerf: RecommendationPerformance | null | undefined,
  direction: 'long' | 'short',
  score: number,
  horizon: '1d' | '3d' | '5d' = '5d'
): SignalTrust | null {
  if (!recPerf?.per_bucket) return null;
  const band = score >= (recPerf.high_score ?? 7) ? 'hi' : 'lo';
  const stats = recPerf.per_bucket[`${direction}_${band}`];
  if (!stats) return null;
  const h = horizonStats(stats, horizon);
  const hit = h?.hit_rate ?? null;
  const n = h?.evaluated ?? 0;
  const g = grade(hit, n);
  const hitPct = hit != null ? hit * 100 : null;
  return {
    grade: g,
    hitRate: hitPct,
    n,
    fired: stats.count,
    avgReturn: h?.avg_return_pct ?? null,
    label: describe(g, hitPct, n, h?.avg_return_pct ?? null)
  };
}

/** True when low-score picks beat high-score ones — the conviction number is
 * currently inverted and the UI should say so out loud. */
export function scoreInverted(
  recPerf: RecommendationPerformance | null | undefined,
  direction: 'long' | 'short' = 'long',
  horizon: '1d' | '3d' | '5d' = '5d'
): boolean {
  const hi = horizonStats(recPerf?.per_bucket?.[`${direction}_hi`], horizon);
  const lo = horizonStats(recPerf?.per_bucket?.[`${direction}_lo`], horizon);
  if (!hi || !lo || hi.hit_rate == null || lo.hit_rate == null) return false;
  if ((hi.evaluated ?? 0) < MIN_N || (lo.evaluated ?? 0) < MIN_N) return false;
  return lo.hit_rate > hi.hit_rate + 0.03; // 3pt margin so it doesn't flap
}

export const GRADE_CLASS: Record<TrustGrade, string> = {
  trusted: 'text-signal-up',
  unproven: 'text-zinc-500',
  noise: 'text-signal-down'
};
