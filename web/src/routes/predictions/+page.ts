import { loadPredictions, loadPredictionPerformance } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [predictions, perf] = await Promise.all([
    loadPredictions(fetch),
    loadPredictionPerformance(fetch)
  ]);
  return { predictions, perf };
};
