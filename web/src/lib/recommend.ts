// Momentum-quality recommendation scoring. Frontend-only: ranks the live
// scan rows into long and short pick lists. Rewards confirmed momentum
// (volume, MACD, VWAP, RSI trend zone) and news-backed catalysts; the
// scanner's "stretched" caution_level disqualifies a row as a late entry.
import type { ScanRow } from './types';

export type RecDirection = 'long' | 'short';

export interface Recommendation {
  ticker: string;
  row: ScanRow;
  direction: RecDirection;
  score: number;
  reasons: string[];
  cautions: string[];
}

const MIN_SCORE = 5;
const MAX_PER_SIDE = 6;

function scoreRow(row: ScanRow, dir: RecDirection): Recommendation | null {
  const p1 = row.pct_1d;
  if (p1 == null || p1 === 0) return null;

  // A favorable move is positive when price action agrees with the trade.
  const long = dir === 'long';
  const fav1 = long ? p1 : -p1;
  if (fav1 <= 0) return null;

  // "stretched" means the move is already exhausted — never a fresh entry.
  if (row.caution_level === 'stretched') return null;

  let score = 0;
  const reasons: string[] = [];
  const cautions: string[] = [];
  const moveSign = long ? '+' : '-';

  // Day move: enough to signal momentum, not so far it's a chase.
  if (fav1 >= 1.5 && fav1 < 5) {
    score += 2;
    reasons.push(`${moveSign}${fav1.toFixed(1)}% today`);
  } else if ((fav1 > 0 && fav1 < 1.5) || (fav1 >= 5 && fav1 < 9)) {
    score += 1;
    reasons.push(`${moveSign}${fav1.toFixed(1)}% today`);
  }

  // 5-day trend in the same direction (but not already parabolic).
  const p5 = row.pct_5d;
  if (p5 != null) {
    const fav5 = long ? p5 : -p5;
    if (fav5 >= 1 && fav5 < 18) {
      score += 1;
      reasons.push(`5d ${long ? 'uptrend' : 'downtrend'} ${p5 > 0 ? '+' : ''}${p5.toFixed(0)}%`);
    }
  }

  // Volume confirmation.
  const rv = row.rel_volume;
  if (rv != null) {
    if (rv >= 2) {
      score += 2;
      reasons.push(`${rv.toFixed(1)}x volume`);
    } else if (rv >= 1.5) {
      score += 1;
      reasons.push(`${rv.toFixed(1)}x volume`);
    }
  }

  // MACD: a fresh cross is the strongest trend signal; histogram is weaker.
  const wantCross = long ? 'bullish' : 'bearish';
  if (row.macd_cross === wantCross) {
    score += 2;
    reasons.push(`MACD ${wantCross} cross`);
  } else if (row.macd_hist != null && (long ? row.macd_hist > 0 : row.macd_hist < 0)) {
    score += 1;
    reasons.push(`MACD ${long ? 'positive' : 'negative'}`);
  }

  // Intraday strength holding on the right side of VWAP.
  const aboveVwap = row.intraday?.above_vwap;
  if (long && aboveVwap === true) {
    score += 1;
    reasons.push('above VWAP');
  } else if (!long && aboveVwap === false) {
    score += 1;
    reasons.push('below VWAP');
  }

  // RSI: reward the trend zone, penalize the exhausted extreme.
  const rsi = row.rsi_14;
  if (rsi != null) {
    if (long) {
      if (rsi >= 55 && rsi <= 72) {
        score += 1;
        reasons.push(`RSI ${rsi.toFixed(0)} trending`);
      } else if (rsi > 80) {
        score -= 2;
        cautions.push(`RSI ${rsi.toFixed(0)} overbought`);
      } else if (rsi > 75) {
        score -= 1;
        cautions.push(`RSI ${rsi.toFixed(0)} elevated`);
      }
    } else {
      if (rsi >= 28 && rsi <= 45) {
        score += 1;
        reasons.push(`RSI ${rsi.toFixed(0)} weak`);
      } else if (rsi < 20) {
        score -= 2;
        cautions.push(`RSI ${rsi.toFixed(0)} oversold`);
      } else if (rsi < 25) {
        score -= 1;
        cautions.push(`RSI ${rsi.toFixed(0)} washed out`);
      }
    }
  }

  // News catalyst — a synthesis-confirmed move is the highest-quality signal.
  const syn = row.synthesis;
  if (syn) {
    if (syn.verdict === 'news_explains_move') {
      score += syn.confidence === 'high' ? 3 : 2;
      reasons.push(syn.confidence === 'high' ? 'news-confirmed catalyst' : 'news-driven move');
    } else if (syn.verdict === 'partial_explanation') {
      score += 1;
      reasons.push('partly news-driven');
    } else if (syn.verdict === 'move_unexplained_by_news') {
      score -= 1;
      cautions.push('unexplained move');
    }
  } else if (row.news_count != null && row.news_count > 0) {
    score += 1;
    reasons.push(`${row.news_count} fresh ${row.news_count === 1 ? 'headline' : 'headlines'}`);
  }

  // An "extended" move is a worse entry, but not disqualifying like "stretched".
  if (row.caution_level === 'caution') {
    score -= 2;
    cautions.push('extended');
  }

  if (score < MIN_SCORE) return null;
  return { ticker: row.ticker, row, direction: dir, score, reasons, cautions };
}

export function recommend(rows: ScanRow[]): {
  longs: Recommendation[];
  shorts: Recommendation[];
} {
  const longs: Recommendation[] = [];
  const shorts: Recommendation[] = [];
  for (const row of rows) {
    const long = scoreRow(row, 'long');
    if (long) longs.push(long);
    const short = scoreRow(row, 'short');
    if (short) shorts.push(short);
  }
  const byScore = (a: Recommendation, b: Recommendation) =>
    b.score - a.score || (b.row.rel_volume ?? 0) - (a.row.rel_volume ?? 0);
  longs.sort(byScore);
  shorts.sort(byScore);
  return { longs: longs.slice(0, MAX_PER_SIDE), shorts: shorts.slice(0, MAX_PER_SIDE) };
}
