import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const ssr = false;
export const prerender = false;

// Route folded into the home feed (see lib/feed.ts); per-ticker slices live
// on /t/[ticker].
export const load: PageLoad = () => {
  redirect(307, "/");
};
