<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { browser } from '$app/environment';
  import { startScanWatch } from '$lib/freshness';
  import ThemeToggle from './ThemeToggle.svelte';
  import SearchBox from './SearchBox.svelte';
  let { children } = $props();

  // The dashboard's pulse: refetch scan.json's generated_at on tab-resume and
  // every 5 minutes; invalidate all loads when a new scan lands.
  if (browser) startScanWatch();
</script>

<div class="mx-auto flex min-h-screen max-w-screen-xl flex-col px-4 sm:px-6 lg:px-8 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))]">
  <header class="mb-4 flex items-center justify-between gap-2">
    <a href="/" class="group flex items-center gap-2">
      <span class="grid h-8 w-8 place-items-center rounded-md bg-signal-info/10 text-signal-info">
        <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 17l5-5 4 4 8-8" stroke-linecap="round" stroke-linejoin="round" />
          <path d="M14 8h6v6" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </span>
      <div class="leading-tight">
        <div class="font-semibold tracking-tight">Momentum</div>
        <div class="hidden text-[10px] uppercase tracking-wider text-zinc-500 sm:block">scanner · news · macro</div>
      </div>
    </a>
    <nav class="flex items-center gap-1 text-xs">
      <a
        href="/"
        class="rounded px-2.5 py-1.5 transition-colors {$page.url.pathname === '/' ? 'bg-ink-700 text-zinc-100' : 'text-zinc-400 hover:bg-ink-800'}"
        >Scan</a
      >
      <a
        href="/review"
        class="rounded px-2.5 py-1.5 transition-colors {$page.url.pathname.startsWith('/review') ? 'bg-ink-700 text-zinc-100' : 'text-zinc-400 hover:bg-ink-800'}"
        >Review</a
      >
      <span class="mx-1 h-4 w-px bg-ink-700"></span>
      <SearchBox />
      <ThemeToggle />
    </nav>
  </header>
  <main class="flex-1">
    {@render children()}
  </main>
  <footer class="mt-8 flex items-center justify-between border-t border-ink-700 pt-4 text-[10px] uppercase tracking-wider text-zinc-500">
    <span>Personal scanner. Not investment advice.</span>
    <span class="flex items-center gap-3">
      <a href="/learn" class="hover:text-zinc-300">Learn</a>
      <a href="https://github.com/3243dwon/Momomentum" class="hover:text-zinc-300">source</a>
    </span>
  </footer>
</div>
