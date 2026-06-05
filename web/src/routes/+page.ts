import { loadAll, loadTrumpPulse, loadSerenity } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [all, pulse, serenity] = await Promise.all([
    loadAll(fetch),
    loadTrumpPulse(fetch),
    loadSerenity(fetch)
  ]);
  return { ...all, pulse, serenity };
};
