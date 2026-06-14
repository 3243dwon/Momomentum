// Normalize ScanRow + delta/news/watchlist signals into the spec's flag
// vocabulary. IconCluster reads from this single array so we don't sprinkle
// per-signal conditionals across the templates.

import type { ScanRow, RankJump } from './types';

export type TickerFlag =
  | 'trump-mention'
  | 'extended'
  | 'overbought'
  | 'stretched'
  | 'new-top-20'
  | 'volume-spike'
  | 'macd-up'
  | 'macd-down'
  | 'rank-jump'
  | 'watchlist'
  | 'news-hot';

export interface FlagInput {
  row: ScanRow;
  isNewEntrant?: boolean;
  isAccel?: boolean;
  pinned?: boolean;
  jump?: RankJump;
  newsHigh?: boolean;
  trumpMention?: boolean;
}

// Order here = display priority. IconCluster shows the first N, truncates rest.
// Tuned so the most action-relevant signals (Trump mention, stretched,
// news-hot, volume) win over cosmetic ones (watchlist star, sector tier).
// trump-mention is first — it's rare and high-signal, never truncate it.
const PRIORITY: TickerFlag[] = [
  'trump-mention',
  'stretched',
  'news-hot',
  'volume-spike',
  'new-top-20',
  'rank-jump',
  'macd-up',
  'macd-down',
  'overbought',
  'extended',
  'watchlist'
];

export function flagsFor(input: FlagInput): TickerFlag[] {
  const { row, isNewEntrant, isAccel, pinned, jump, newsHigh, trumpMention } = input;
  const out = new Set<TickerFlag>();

  if (trumpMention) out.add('trump-mention');

  if (row.caution_level === 'stretched') out.add('stretched');
  else if (row.caution_level === 'caution') out.add('extended');

  if (row.flags.includes('overbought')) out.add('overbought');
  if (row.flags.includes('unusual_volume') || (row.rel_volume ?? 0) >= 2) out.add('volume-spike');
  if (row.macd_cross === 'bullish') out.add('macd-up');
  else if (row.macd_cross === 'bearish') out.add('macd-down');

  if (isNewEntrant) out.add('new-top-20');
  if (jump || isAccel) out.add('rank-jump');
  // Note: 'pinned' is intentionally not added here — TickerRow renders the ★
  // inline next to the ticker name, so duplicating it in the cluster is noise.
  if (newsHigh) out.add('news-hot');
  void pinned;

  return PRIORITY.filter((f) => out.has(f));
}

// Short uppercase labels — readable at a glance without needing a legend.
// `tip` is the long-form explanation shown on hover for anyone who wants to
// know what "LATE" or "OB" actually means.
export const FLAG_META: Record<TickerFlag, { label: string; tip: string; tone: Tone }> = {
  'trump-mention':{ label: 'TRUMP', tip: 'Mentioned by Trump on Truth Social recently',                                        tone: 'trump' },
  stretched:     { label: 'LATE',  tip: 'Late entry risk — price is stretched well above its trend, chasing here is risky',  tone: 'down' },
  'news-hot':    { label: 'NEWS',  tip: 'High-impact news headline today',                                                    tone: 'warn' },
  'volume-spike':{ label: 'VOL',   tip: 'Volume is at least 2x its 20-day average — institutions are active',                tone: 'warn' },
  'new-top-20':  { label: 'NEW',   tip: 'New entrant to the Top 20 since the last scan',                                      tone: 'info' },
  'rank-jump':   { label: 'JUMP',  tip: 'Big rank jump or accelerating momentum vs. the last scan',                           tone: 'info' },
  'macd-up':     { label: 'MACD↑', tip: 'MACD bullish cross — momentum turning up',                                           tone: 'up' },
  'macd-down':   { label: 'MACD↓', tip: 'MACD bearish cross — momentum turning down',                                         tone: 'down' },
  overbought:    { label: 'OB',    tip: 'Overbought (RSI > 70) — short-term pullback risk',                                  tone: 'warn' },
  extended:      { label: 'EXT',   tip: 'Extended above moving averages — minor caution, not a strong sell signal',          tone: 'warn' },
  watchlist:     { label: '★',     tip: 'On your watchlist',                                                                  tone: 'mute' }
};

export type Tone = 'up' | 'down' | 'warn' | 'info' | 'mute' | 'trump';

export const TONE_CLASS: Record<Tone, string> = {
  up:    'text-signal-up',
  down:  'text-signal-down',
  warn:  'text-signal-warn',
  info:  'text-signal-info',
  mute:  'text-zinc-500',
  // Purple (signal-pred) is outside the green/red/amber/blue signal palette,
  // so the TRUMP chip reads as "notable / special" rather than good/bad/caution.
  // NB: IconCluster's TONE_BG is keyed by this exact class string.
  trump: 'text-signal-pred'
};
