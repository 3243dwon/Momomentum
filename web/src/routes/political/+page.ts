import { loadPolitical, loadScan, loadTrumpPulse, loadWatchlist } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [political, scan, watchlist, pulse] = await Promise.all([
    loadPolitical(fetch),
    loadScan(fetch),
    loadWatchlist(fetch),
    loadTrumpPulse(fetch)
  ]);
  return { political, scan, watchlist, pulse };
};
