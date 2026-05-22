import { loadPerformance, loadRecommendationPerformance } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [perf, recPerf] = await Promise.all([
    loadPerformance(fetch),
    loadRecommendationPerformance(fetch)
  ]);
  return { perf, recPerf };
};
