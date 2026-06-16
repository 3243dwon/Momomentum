import { loadPredictions, loadPredictionPerformance, loadDeals } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

// The forward-call tier's front door: the live ripple calls (predictions.json,
// the ungraded "before" calls), the recent graded calls grouped by catalyst
// (deals.json), and the aggregate track record (prediction_performance.json).
// All three are small static JSON — await them together so the page renders
// complete rather than streaming section by section.
export const load: PageLoad = async ({ fetch }) => {
  const [predictions, predPerf, deals] = await Promise.all([
    loadPredictions(fetch),
    loadPredictionPerformance(fetch),
    loadDeals(fetch)
  ]);
  return { predictions, predPerf, deals };
};
