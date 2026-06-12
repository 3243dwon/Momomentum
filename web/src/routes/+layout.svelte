<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { browser } from '$app/environment';
  import { startScanWatch, regimeLabel, scanGeneratedAt, now, staleness, type StaleLevel } from '$lib/freshness';
  import ThemeToggle from './ThemeToggle.svelte';
  import SearchBox from './SearchBox.svelte';
  let { children } = $props();

  // The dashboard's pulse: refetch scan.json's generated_at on tab-resume and
  // every 5 minutes; invalidate all loads when a new scan lands.
  if (browser) startScanWatch();

  const REGIME_TINT: Record<string, string> = {
    risk_on: 'bg-signal-up',
    risk_off: 'bg-signal-down',
    mixed: 'bg-signal-warn'
  };

  // Weather layer: regime colors the sky, scan age sets its brightness.
  // Written as custom properties on <html> so the CSS scroll scrub never
  // touches JS; var(--signal-*) references stay theme-correct on toggle.
  const WEATHER_RGB: Record<string, string> = {
    risk_on: 'var(--signal-up)',
    risk_off: 'var(--signal-down)',
    mixed: 'var(--signal-warn)'
  };
  const WEATHER_DIM: Record<StaleLevel, number> = { fresh: 1, aging: 0.55, stale: 0.15 };

  $effect(() => {
    const rgb = $regimeLabel ? WEATHER_RGB[$regimeLabel] : undefined;
    const base = rgb ? ($regimeLabel === 'mixed' ? 0.045 : 0.05) : 0.06;
    // null generated_at means "not fetched yet", not "stale" — keep full light.
    const dim = $scanGeneratedAt ? WEATHER_DIM[staleness($scanGeneratedAt, $now).level] : 1;
    const root = document.documentElement.style;
    root.setProperty('--weather-rgb', rgb ?? '59 130 246');
    root.setProperty('--weather-alpha', String(base * dim));
  });
</script>

<!-- Regime weather: the sky is the tape — a fixed glow behind everything,
     colored by the $effect above, receding via the CSS scroll timeline. -->
<div class="weather" aria-hidden="true"></div>

<!-- Regime tint: the market state registers before anything is read. -->
{#if $regimeLabel && REGIME_TINT[$regimeLabel]}
  <div class="fixed inset-x-0 top-0 z-50 h-[2px] {REGIME_TINT[$regimeLabel]} opacity-80" title="regime: {$regimeLabel}"></div>
{/if}

<div class="mx-auto flex min-h-screen max-w-screen-xl flex-col px-4 sm:px-6 lg:px-8 pt-[max(1rem,env(safe-area-inset-top))] pb-[calc(4.5rem+env(safe-area-inset-bottom))] sm:pb-[max(1rem,env(safe-area-inset-bottom))]">
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
      <!-- Text links live in the header on desktop; on phones they move to
           the thumb-reach bottom tab bar below. -->
      <a
        href="/"
        class="hidden rounded px-2.5 py-1.5 transition-colors sm:block {$page.url.pathname === '/' ? 'bg-ink-700 text-zinc-100' : 'text-zinc-400 hover:bg-ink-800'}"
        >Scan</a
      >
      <a
        href="/ask"
        class="hidden rounded px-2.5 py-1.5 transition-colors sm:block {$page.url.pathname.startsWith('/ask') ? 'bg-ink-700 text-zinc-100' : 'text-zinc-400 hover:bg-ink-800'}"
        >Ask</a
      >
      <a
        href="/deals"
        class="hidden rounded px-2.5 py-1.5 transition-colors sm:block {$page.url.pathname.startsWith('/deals') ? 'bg-ink-700 text-zinc-100' : 'text-zinc-400 hover:bg-ink-800'}"
        >Deals</a
      >
      <a
        href="/review"
        class="hidden rounded px-2.5 py-1.5 transition-colors sm:block {$page.url.pathname.startsWith('/review') ? 'bg-ink-700 text-zinc-100' : 'text-zinc-400 hover:bg-ink-800'}"
        >Review</a
      >
      <span class="mx-1 hidden h-4 w-px bg-ink-700 sm:block"></span>
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
      <a href="/anatomy" class="hover:text-zinc-300">How an alert is made</a>
      <a href="/learn" class="hover:text-zinc-300">Learn</a>
      <a href="https://github.com/3243dwon/Momomentum" class="hover:text-zinc-300">source</a>
    </span>
  </footer>
</div>

<!-- Phone tab bar: thumb-reach nav for the PWA. Hidden from sm: up. -->
<nav class="fixed inset-x-0 bottom-0 z-30 border-t border-ink-700 bg-ink-900/95 backdrop-blur pb-[env(safe-area-inset-bottom)] sm:hidden">
  <div class="mx-auto flex max-w-screen-xl">
    {#each [
      { href: '/', label: 'Scan', active: $page.url.pathname === '/', icon: 'M3 17l5-5 4 4 8-8M14 8h6v6' },
      { href: '/ask', label: 'Ask', active: $page.url.pathname.startsWith('/ask'), icon: 'M8 10h8M8 14h5M21 12a8.96 8.96 0 01-9 9 8.96 8.96 0 01-4.2-1L3 21l1-4.8A8.96 8.96 0 013 12a9 9 0 1118 0z' },
      { href: '/deals', label: 'Deals', active: $page.url.pathname.startsWith('/deals'), icon: 'M9 15l6-6M10.5 7.5l1-1a3.5 3.5 0 015 5l-1 1M13.5 16.5l-1 1a3.5 3.5 0 01-5-5l1-1' },
      { href: '/review', label: 'Review', active: $page.url.pathname.startsWith('/review'), icon: 'M9 5h6m-7 4h8m-8 4h8m-8 4h5M6 3h12a1 1 0 011 1v16a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z' }
    ] as item (item.href)}
      <a
        href={item.href}
        class="flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] uppercase tracking-wider transition-colors {item.active ? 'text-signal-info' : 'text-zinc-500 active:text-zinc-300'}"
      >
        <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d={item.icon} />
        </svg>
        {item.label}
      </a>
    {/each}
  </div>
</nav>
