import { loadDeals } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const deals = await loadDeals(fetch);
  return { deals };
};
