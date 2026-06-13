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

export const load: PageLoad = ({ fetch }) => {
  // Don't await — hand SvelteKit a pending promise so navigation completes
  // immediately and the page shell renders. The six JSON files (one ~210KB)
  // then stream in and populate each section as they land, instead of the
  // whole route blocking on the slowest fetch (or never opening if one stalls).
  const review = Promise.all([
    loadWeekly(fetch),
    loadPerformance(fetch),
    loadRecommendationPerformance(fetch),
    loadDeskPerformance(fetch),
    loadPredictionPerformance(fetch),
    loadLedger(fetch)
  ]).then(([weekly, perf, recPerf, deskPerf, predPerf, ledger]) => ({
    weekly,
    perf,
    recPerf,
    deskPerf,
    predPerf,
    ledger
  }));
  return { review };
};
