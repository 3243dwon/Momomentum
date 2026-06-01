import { loadAll, loadTrumpPulse } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [all, pulse] = await Promise.all([loadAll(fetch), loadTrumpPulse(fetch)]);
  return { ...all, pulse };
};
