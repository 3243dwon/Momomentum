import { loadPolitical, loadScan, loadWatchlist } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [political, scan, watchlist] = await Promise.all([
    loadPolitical(fetch),
    loadScan(fetch),
    loadWatchlist(fetch)
  ]);
  return { political, scan, watchlist };
};
