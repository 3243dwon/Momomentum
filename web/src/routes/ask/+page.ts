import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

// No data loading here — /api/ask pulls the committed JSON server-side per
// question. We only read the optional ?q= prefill so links can land on the
// page with a question already typed (never auto-submitted).
export const load: PageLoad = ({ url }) => {
  return { q: url.searchParams.get('q') ?? '' };
};
