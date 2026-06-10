import {
  loadAll,
  loadTrumpPulse,
  loadSerenity,
  loadPredictions,
  loadPerformance,
  loadRecommendationPerformance,
  loadBriefing
} from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [all, pulse, serenity, predictions, performance, recPerf, briefing] = await Promise.all([
    loadAll(fetch),
    loadTrumpPulse(fetch),
    loadSerenity(fetch),
    loadPredictions(fetch),
    loadPerformance(fetch),
    loadRecommendationPerformance(fetch),
    loadBriefing(fetch)
  ]);
  return { ...all, pulse, serenity, predictions, performance, recPerf, briefing };
};
