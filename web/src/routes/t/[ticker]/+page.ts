import {
  loadAll,
  loadPredictions,
  loadWeekly,
  loadPolitical,
  loadSerenity,
  loadTrumpPulse,
  loadLedger
} from '$lib/api';
import { buildFeed, feedForTicker } from '$lib/feed';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ params, fetch }) => {
  const [all, preds, weekly, political, serenity, pulse, ledger] = await Promise.all([
    loadAll(fetch),
    loadPredictions(fetch),
    loadWeekly(fetch),
    loadPolitical(fetch),
    loadSerenity(fetch),
    loadTrumpPulse(fetch),
    loadLedger(fetch)
  ]);
  const ticker = params.ticker.toUpperCase();
  const row = all.scan?.rows.find((r) => r.ticker === ticker) ?? null;
  const news = all.news?.ticker_news[ticker] ?? [];
  const macroMentions = (all.news?.macro_events ?? []).filter(
    (m) =>
      m.beneficiaries.some((b) => b.ticker.toUpperCase() === ticker) ||
      m.losers.some((l) => l.ticker.toUpperCase() === ticker)
  );

  // Ripple predictions: ones ABOUT this ticker (it's the predicted mover), and
  // ones this ticker TRIGGERED (its news is rippling out to other names).
  const allPreds = preds?.predictions ?? [];
  const predictionsAbout = allPreds.filter((p) => p.ticker.toUpperCase() === ticker);
  const predictionsFrom = allPreds.filter(
    (p) => p.trigger_ticker.toUpperCase() === ticker && p.ticker.toUpperCase() !== ticker
  );

  // Unified intel feed sliced to this ticker. Predictions and macro events get
  // their own richer sections on the page, so the feed keeps only the kinds
  // that would otherwise have nowhere to live: news, Serenity, Trump mentions.
  const feed = feedForTicker(
    buildFeed({ news: all.news, serenity, predictions: preds, pulse, limit: Infinity }),
    ticker
  )
    .filter((i) => i.kind === 'news' || i.kind === 'serenity' || i.kind === 'trump')
    .slice(0, 15);

  const weeklyEntry = weekly?.analyses.find((a) => a.ticker.toUpperCase() === ticker) ?? null;
  const weekEnding = weekly?.week_ending ?? null;
  const congressTrades = political?.by_ticker?.[ticker] ?? [];

  // null = ledger.json absent (omit the section); [] = file exists, no calls.
  const ledgerEntries = ledger
    ? ledger.entries
        .filter((e) => e.ticker.toUpperCase() === ticker)
        .sort((a, b) => b.ts.localeCompare(a.ts))
        .slice(0, 20)
    : null;

  return {
    ticker,
    row,
    scan: all.scan,
    news,
    macroMentions,
    predictionsAbout,
    predictionsFrom,
    feed,
    weeklyEntry,
    weekEnding,
    congressTrades,
    ledgerEntries,
    pulse
  };
};
