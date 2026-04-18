// Data loaders. Static JSON shipped via Vite static folder; cache-bust by
// pinning the URL with the file's generated_at when refetching client-side.
import type { ScanData, NewsData, DeltaData, Watchlist, WeeklyData } from './types';

type Fetch = typeof fetch;

async function getJson<T>(fetch: Fetch, path: string): Promise<T | null> {
  try {
    const r = await fetch(`/data/${path}`, { cache: 'no-store' });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function loadScan(fetch: Fetch) {
  return getJson<ScanData>(fetch, 'scan.json');
}

export async function loadNews(fetch: Fetch) {
  return getJson<NewsData>(fetch, 'news.json');
}

export async function loadDeltas(fetch: Fetch) {
  return getJson<DeltaData>(fetch, 'deltas.json');
}

export async function loadWatchlist(fetch: Fetch) {
  return getJson<Watchlist>(fetch, 'watchlist.json');
}

export async function loadWeekly(fetch: Fetch) {
  return getJson<WeeklyData>(fetch, 'weekly.json');
}

export async function loadAll(fetch: Fetch) {
  const [scan, news, deltas, watchlist] = await Promise.all([
    loadScan(fetch),
    loadNews(fetch),
    loadDeltas(fetch),
    loadWatchlist(fetch)
  ]);
  return { scan, news, deltas, watchlist };
}
