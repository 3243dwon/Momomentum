// The unified intel feed: news, Serenity posts, ripple predictions, macro
// events, and Trump ticker mentions are all the same shape — a timestamped
// item about tickers — so the home page renders them in one chronological
// stream instead of five differently-styled sections.
import type {
  NewsData,
  SerenityData,
  PredictionsData,
  TrumpPulseData
} from './types';

export type FeedKind = 'news' | 'serenity' | 'prediction' | 'macro' | 'trump';

export interface FeedItem {
  id: string;
  kind: FeedKind;
  ts: string; // ISO — items without a timestamp inherit their file's generated_at
  tickers: string[];
  title: string;
  detail?: string;
  stance?: 'bull' | 'bear' | 'neutral';
  confidence?: string;
  horizon?: string;
  badge?: string; // e.g. "not yet priced in"
  impact?: string;
  url?: string | null;
  via?: string; // trigger ticker for ripple predictions
}

export const KIND_META: Record<FeedKind, { label: string; chip: string }> = {
  news: { label: 'News', chip: 'bg-ink-700 text-zinc-300' },
  serenity: { label: '🧠 Serenity', chip: 'bg-signal-info/15 text-signal-info' },
  prediction: { label: '🔮 Predict', chip: 'bg-signal-pred/15 text-signal-pred' },
  macro: { label: 'Macro', chip: 'bg-signal-warn/15 text-signal-warn' },
  trump: { label: 'Trump', chip: 'bg-signal-down/15 text-signal-down' }
};

export function buildFeed(opts: {
  news?: NewsData | null;
  serenity?: SerenityData | null;
  predictions?: PredictionsData | null;
  pulse?: TrumpPulseData | null;
  limit?: number;
}): FeedItem[] {
  const items: FeedItem[] = [];
  const seen = new Set<string>();

  for (const [ticker, list] of Object.entries(opts.news?.ticker_news ?? {})) {
    for (const n of list) {
      if (seen.has(n.id)) continue; // same story can hang off several tickers
      seen.add(n.id);
      items.push({
        id: `news:${n.id}`,
        kind: 'news',
        ts: n.published_at,
        tickers: [n.ticker ?? ticker],
        title: n.title,
        impact: n.impact,
        url: n.url
      });
    }
  }

  for (const ev of opts.news?.macro_events ?? []) {
    items.push({
      id: `macro:${ev.dedup_group}`,
      kind: 'macro',
      ts: opts.news?.generated_at ?? '',
      tickers: [
        ...ev.beneficiaries.map((b) => b.ticker),
        ...ev.losers.map((l) => l.ticker)
      ].slice(0, 6),
      title: ev.event_summary,
      detail: ev.headlines[0]
    });
  }

  for (const t of opts.serenity?.tweets ?? []) {
    items.push({
      id: `serenity:${t.id}`,
      kind: 'serenity',
      ts: t.createdAt,
      tickers: t.tickers,
      title: t.summaryEn || t.text,
      stance: t.stance,
      url: t.url
    });
  }

  for (const p of opts.predictions?.predictions ?? []) {
    items.push({
      id: `pred:${p.trigger_ticker}:${p.ticker}`,
      kind: 'prediction',
      ts: p.created_at ?? opts.predictions?.generated_at ?? '',
      tickers: [p.ticker],
      title: p.rationale,
      detail: p.event_summary,
      stance: p.direction === 'bullish' ? 'bull' : 'bear',
      confidence: p.confidence,
      horizon: p.horizon,
      badge: p.priced_in === 'no' ? 'not yet priced in' : p.priced_in === 'contradicted' ? 'tape disagrees' : undefined,
      via: p.trigger_ticker,
      url: p.news_url
    });
  }

  // Trump posts only earn a slot when they actually name tickers.
  for (const post of opts.pulse?.truth_posts ?? []) {
    if (!post.ticker_mentions?.length || !post.ts) continue;
    items.push({
      id: `trump:${post.ts}`,
      kind: 'trump',
      ts: post.ts,
      tickers: post.ticker_mentions,
      title: post.text.length > 200 ? post.text.slice(0, 200) + '…' : post.text,
      url: post.url
    });
  }

  items.sort((a, b) => (b.ts || '').localeCompare(a.ts || ''));
  return items.slice(0, opts.limit ?? 40);
}

/** Per-ticker slice for the /t/[ticker] hub. */
export function feedForTicker(items: FeedItem[], ticker: string): FeedItem[] {
  const t = ticker.toUpperCase();
  return items.filter((i) => i.tickers.includes(t) || i.via === t);
}
