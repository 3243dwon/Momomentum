import { loadPerformance, loadRecommendationPerformance, loadDeskPerformance } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [perf, recPerf, deskPerf] = await Promise.all([
    loadPerformance(fetch),
    loadRecommendationPerformance(fetch),
    loadDeskPerformance(fetch)
  ]);
  return { perf, recPerf, deskPerf };
};
