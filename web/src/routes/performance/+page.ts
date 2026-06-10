import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const ssr = false;
export const prerender = false;

// Merged into /review — weekly verdicts + signal scoreboard + ledger.
export const load: PageLoad = () => {
  redirect(307, "/review");
};
