import { loadAll } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ params, fetch }) => {
  const all = await loadAll(fetch);
  const ticker = params.ticker.toUpperCase();
  const row = all.scan?.rows.find((r) => r.ticker === ticker) ?? null;
  const news = all.news?.ticker_news[ticker] ?? [];
  const macroMentions = (all.news?.macro_events ?? []).filter(
    (m) =>
      m.beneficiaries.some((b) => b.ticker.toUpperCase() === ticker) ||
      m.losers.some((l) => l.ticker.toUpperCase() === ticker)
  );
  return { ticker, row, news, macroMentions, scan: all.scan };
};
