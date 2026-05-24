// Normalize ScanRow + delta/news/watchlist signals into the spec's flag
// vocabulary. IconCluster reads from this single array so we don't sprinkle
// per-signal conditionals across the templates.

import type { ScanRow, RankJump } from './types';

export type TickerFlag =
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
}

// Order here = display priority. IconCluster shows the first N, truncates rest.
// Tuned so the most action-relevant signals (stretched, news-hot, volume) win
// over cosmetic ones (watchlist star, sector tier).
const PRIORITY: TickerFlag[] = [
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
  const { row, isNewEntrant, isAccel, pinned, jump, newsHigh } = input;
  const out = new Set<TickerFlag>();

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

// Display metadata. Glyphs picked for legibility in a 12-14px cell — no script
// faces, no emoji (emoji break layout in Firefox/Chrome at small sizes).
export const FLAG_META: Record<TickerFlag, { glyph: string; label: string; tone: Tone }> = {
  stretched:     { glyph: '▼', label: 'stretched · late entry',  tone: 'down' },
  'news-hot':    { glyph: '◉', label: 'high-impact news',         tone: 'warn' },
  'volume-spike':{ glyph: '⚡', label: 'volume spike',             tone: 'warn' },
  'new-top-20':  { glyph: '◆', label: 'new in top-20',            tone: 'info' },
  'rank-jump':   { glyph: '↑', label: 'rank jump',                tone: 'info' },
  'macd-up':     { glyph: '↗', label: 'MACD bullish cross',       tone: 'up' },
  'macd-down':   { glyph: '↘', label: 'MACD bearish cross',       tone: 'down' },
  overbought:    { glyph: '◎', label: 'overbought',               tone: 'warn' },
  extended:      { glyph: '▲', label: 'extended',                 tone: 'warn' },
  watchlist:     { glyph: '★', label: 'on watchlist',             tone: 'mute' }
};

export type Tone = 'up' | 'down' | 'warn' | 'info' | 'mute';

export const TONE_CLASS: Record<Tone, string> = {
  up:   'text-signal-up',
  down: 'text-signal-down',
  warn: 'text-signal-warn',
  info: 'text-signal-info',
  mute: 'text-zinc-500'
};
