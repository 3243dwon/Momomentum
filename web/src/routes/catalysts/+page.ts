import { loadCatalysts, loadScan } from '$lib/api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

// The portfolio catalyst calendar (catalysts.json) plus the live scan (scan.json)
// so each holding's row can show its current price / day move next to the dated
// catalysts. Both small static JSON — await together so the page renders whole.
export const load: PageLoad = async ({ fetch }) => {
  const [catalysts, scan] = await Promise.all([loadCatalysts(fetch), loadScan(fetch)]);
  return { catalysts, scan };
};
