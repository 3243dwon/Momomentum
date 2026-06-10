import {
  loadWeekly,
  loadPerformance,
  loadRecommendationPerformance,
  loadDeskPerformance,
  loadPredictionPerformance,
  loadLedger
} from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [weekly, perf, recPerf, deskPerf, predPerf, ledger] = await Promise.all([
    loadWeekly(fetch),
    loadPerformance(fetch),
    loadRecommendationPerformance(fetch),
    loadDeskPerformance(fetch),
    loadPredictionPerformance(fetch),
    loadLedger(fetch)
  ]);
  return { weekly, perf, recPerf, deskPerf, predPerf, ledger };
};
