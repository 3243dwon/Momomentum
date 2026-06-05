import { loadSerenity, loadScan } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async ({ fetch }) => {
  const [serenity, scan] = await Promise.all([loadSerenity(fetch), loadScan(fetch)]);
  return { serenity, scan };
};
