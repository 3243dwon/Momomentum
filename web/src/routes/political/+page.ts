import { loadPolitical, loadScan, loadTrumpPulse, loadTrumpBasket, loadWatchlist } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [political, scan, watchlist, pulse, basket] = await Promise.all([
    loadPolitical(fetch),
    loadScan(fetch),
    loadWatchlist(fetch),
    loadTrumpPulse(fetch),
    loadTrumpBasket(fetch)
  ]);
  return { political, scan, watchlist, pulse, basket };
};
