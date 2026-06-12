// The one real alert /anatomy replays, frozen from committed repo data so the
// story can never drift from the artifacts that produced it. Every constant
// cites the file + commit it was recovered from. Nothing here is synthetic.

/** Scroll bands for the six pinned beats. p = Scrub progress over the track. */
export interface Beat {
  n: number;
  label: string;
  a: number;
  b: number;
}

export const BEATS: Beat[] = [
  { n: 1, label: 'cold open', a: 0, b: 0.16 },
  { n: 2, label: 'classified', a: 0.16, b: 0.36 },
  { n: 3, label: 'the cut', a: 0.36, b: 0.52 },
  { n: 4, label: 'dispatch', a: 0.52, b: 0.7 },
  { n: 5, label: 'the tape', a: 0.7, b: 0.88 },
  { n: 6, label: 'verdict', a: 0.88, b: 1 }
];

// data/news.json @ commit a49c4fc — the scan that fired the alert.
export const NEWS = {
  title: 'Sportradar Stock Rises On Landmark Kalshi Prediction Market Deal',
  publisher: 'benzinga',
  source: 'alpaca',
  published_at: '2026-06-08T17:43:30+00:00',
  type: 'product',
  impact: 'high',
  ticker: 'SRAD'
} as const;

// data/scan.json @ commit a49c4fc.
export const SCAN = {
  generated_at: '2026-06-08 · 15:23 ET',
  universe_size: 5370,
  row_count: 718,
  srad: {
    price: 15.12,
    pct_1d: 8.7,
    rel_volume: 1.26,
    news_count: 1,
    flags: ['big_move'],
    // 20 daily closes ending at the alert.
    spark: [
      12.81, 12.67, 12.46, 12.69, 12.49, 13.12, 13.29, 13.34, 13.01, 13.04,
      13.0, 12.9, 13.05, 13.21, 13.75, 13.68, 13.46, 14.22, 13.9, 15.12
    ]
  }
} as const;

// data/ledger.json @ the 2026-06-10 scan commit — frozen verbatim because the
// entry has since rotated out of the live 500-entry ledger window.
export const LEDGER_ENTRY = {
  id: 'f3f306035455',
  ts: '2026-06-08T19:23:04.606843+00:00',
  kind: 'alert',
  type: 'catalyst',
  ticker: 'SRAD',
  direction: 'long',
  confidence: null,
  price: 15.12,
  thesis: '',
  outcomes: { '1d': 8.47, '3d': null, '5d': null },
  status: 'hit'
} as const;

// data/scan.json @ HEAD commit 0d40ebb — SRAD closes from the entry day's
// official close onward. The entry itself was intraday at 15.12, so 15.26 is
// the same session's close; 16.40 is the +1d close the ledger graded against
// (15.12 -> 16.40 = +8.47%).
export const AFTERMATH_CLOSES = [15.26, 16.4, 16.74, 16.95] as const;

/** One rung of the alert priority ladder. */
export interface LadderRung {
  type: string;
  priority: number;
}

// scanner/alerts/rules.py ALERT_TYPE_PRIORITY, descending.
export const PRIORITY_LADDER: LadderRung[] = [
  { type: 'catalyst', priority: 100 },
  { type: 'ripple', priority: 95 },
  { type: 'macro', priority: 90 },
  { type: 'serenity_match', priority: 85 },
  { type: 'watchlist', priority: 80 },
  { type: 'big_move', priority: 60 },
  { type: 'delta_new_top20', priority: 45 },
  { type: 'delta_rank_jump', priority: 40 },
  { type: 'delta_accel', priority: 35 }
];

// scanner/config.py MAX_STANDARD_ALERTS_PER_SCAN — the hard cap on standard
// alerts (big_move, delta_*) per scan. High-conviction types (catalyst,
// watchlist, macro, serenity_match, ripple) always fire (rules.py two-tier cap).
export const MAX_STANDARD_ALERTS_PER_SCAN = 5;

// data/audit/2026-06-01/alert_152008_trump_pulse.json — a real dispatch that
// failed and was kept anyway. Title's flag emoji stripped for print.
export const FAILED_DISPATCH = {
  ts: '2026-06-01T15:20:08Z',
  title: 'Trump named INTC on Truth Social',
  error: 'FEISHU_WEBHOOK_URL not configured'
} as const;
