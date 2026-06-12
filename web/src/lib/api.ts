// Data loaders. Static JSON shipped via Vite static folder; cache-bust by
// pinning the URL with the file's generated_at when refetching client-side.
import type {
  ScanData,
  NewsData,
  DeltaData,
  Watchlist,
  WeeklyData,
  PerformanceData,
  RecommendationPerformance,
  DeskPerformance,
  PoliticalData,
  TrumpPulseData,
  TrumpBasket,
  SerenityData,
  PredictionsData,
  PredictionPerformance,
  LedgerData,
  BriefingData,
  DealsData
} from './types';

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
  const data = await getJson<NewsData>(fetch, 'news.json');
  if (data) {
    // The scanner's RSS ingest can repeat the same item; dedupe by id so
    // downstream keyed {#each} blocks don't collide on duplicate keys.
    for (const ticker of Object.keys(data.ticker_news)) {
      data.ticker_news[ticker] = [
        ...new Map(data.ticker_news[ticker].map((n) => [n.id, n])).values()
      ];
    }
  }
  return data;
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

export async function loadPerformance(fetch: Fetch) {
  return getJson<PerformanceData>(fetch, 'performance.json');
}

export async function loadRecommendationPerformance(fetch: Fetch) {
  return getJson<RecommendationPerformance>(fetch, 'recommendation_performance.json');
}

export async function loadDeskPerformance(fetch: Fetch) {
  return getJson<DeskPerformance>(fetch, 'desk_performance.json');
}

export async function loadPolitical(fetch: Fetch) {
  return getJson<PoliticalData>(fetch, 'political.json');
}

export async function loadTrumpPulse(fetch: Fetch) {
  return getJson<TrumpPulseData>(fetch, 'trump_pulse.json');
}

export async function loadTrumpBasket(fetch: Fetch) {
  return getJson<TrumpBasket>(fetch, 'trump_basket.json');
}

export async function loadSerenity(fetch: Fetch) {
  return getJson<SerenityData>(fetch, 'serenity.json');
}

export async function loadPredictions(fetch: Fetch) {
  return getJson<PredictionsData>(fetch, 'predictions.json');
}

export async function loadPredictionPerformance(fetch: Fetch) {
  return getJson<PredictionPerformance>(fetch, 'prediction_performance.json');
}

export async function loadLedger(fetch: Fetch) {
  return getJson<LedgerData>(fetch, 'ledger.json');
}

export async function loadBriefing(fetch: Fetch) {
  return getJson<BriefingData>(fetch, 'briefing.json');
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

export async function loadDeals(fetch: Fetch) {
  return getJson<DealsData>(fetch, 'deals.json');
}
