import { loadAll, loadPredictions } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ params, fetch }) => {
  const [all, preds] = await Promise.all([loadAll(fetch), loadPredictions(fetch)]);
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
  return { ticker, row, news, macroMentions, predictionsAbout, predictionsFrom, scan: all.scan };
};
