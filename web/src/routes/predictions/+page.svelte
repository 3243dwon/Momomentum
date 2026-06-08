<script lang="ts">
  import { fmtPct, pctClass } from '$lib/format';
  import type { RipplePrediction, PricedIn } from '$lib/types';

  let { data } = $props();
  const preds: RipplePrediction[] = data.predictions?.predictions ?? [];
  const perf = data.perf;

  // The actionable calls first: names predicted to move that HAVEN'T yet.
  const fresh = preds.filter((p) => p.priced_in === 'no');
  const moving = preds.filter((p) => p.priced_in === 'partial' || p.priced_in === 'yes');
  const contradicted = preds.filter((p) => p.priced_in === 'contradicted');

  const DIR = {
    bullish: { label: '📈 beneficiary', cls: 'text-signal-up' },
    bearish: { label: '📉 at risk', cls: 'text-signal-down' }
  } as const;

  const PRICED: Record<PricedIn, string> = {
    no: 'not yet priced in',
    partial: 'started moving',
    yes: 'already moved',
    contradicted: 'tape disagrees'
  };

  // Honest scoreboard: how the not-yet-priced-in calls actually did at 5 days.
  const freshStat = perf?.by_priced_in?.no?.horizons?.['5d'];
</script>

<svelte:head>
  <title>Ahead of the move — Momentum</title>
</svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">🔮 Ahead of the move</h1>
  <p class="text-xs text-zinc-500">
    Second-order predictions — when a popular stock's news should move <em>other</em> names
    (suppliers, backups, competitors, peers), surfaced before they've priced it in.
  </p>
</header>

{#if freshStat && freshStat.evaluated > 0}
  <div class="card mb-4 flex flex-wrap items-center gap-x-6 gap-y-1 p-3 text-xs">
    <span class="text-[10px] uppercase tracking-wider text-zinc-500"
      >Not-yet-priced-in calls · last {perf?.window_days}d</span
    >
    <span>
      <span class="text-zinc-400">5d hit rate</span>
      <span class="ml-1 font-mono font-semibold">{Math.round((freshStat.hit_rate ?? 0) * 100)}%</span>
    </span>
    <span>
      <span class="text-zinc-400">avg 5d return</span>
      <span class="ml-1 font-mono font-semibold {pctClass(freshStat.avg_return_pct)}"
        >{fmtPct(freshStat.avg_return_pct)}</span
      >
    </span>
    <span class="text-zinc-500">({freshStat.evaluated} evaluated)</span>
    <a
      href="/performance"
      class="ml-auto text-[10px] uppercase tracking-wider text-signal-info hover:underline"
      >Full performance →</a
    >
  </div>
{/if}

{#snippet predCard(p: RipplePrediction)}
  {@const dir = DIR[p.direction]}
  <article class="card p-4">
    <div class="mb-2 flex items-start justify-between gap-2">
      <div class="flex flex-wrap items-center gap-2">
        <a href={`/t/${p.ticker}`} class="font-mono text-sm font-semibold hover:underline {dir.cls}"
          >${p.ticker}</a
        >
        <span class="text-[11px] font-medium {dir.cls}">{dir.label}</span>
        {#if p.pct_1d != null}
          <span class="font-mono text-xs {pctClass(p.pct_1d)}">{fmtPct(p.pct_1d)}</span>
        {:else}
          <span class="text-xs text-zinc-500">flat</span>
        {/if}
      </div>
      <span
        class="whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider {p.priced_in ===
        'no'
          ? 'bg-signal-info/15 text-signal-info'
          : 'text-zinc-500'}">{PRICED[p.priced_in]}</span
      >
    </div>

    <p class="text-sm leading-relaxed text-zinc-200">{p.rationale}</p>

    <div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500">
      <span>
        via <a href={`/t/${p.trigger_ticker}`} class="font-mono text-zinc-300 hover:underline"
          >${p.trigger_ticker}</a
        >
        — {p.event_summary}
      </span>
      <span class="ml-auto flex items-center gap-2">
        <span class="pill">conf {p.confidence}</span>
        <span class="pill">{p.horizon}</span>
        {#if p.news_url}
          <a
            href={p.news_url}
            target="_blank"
            rel="noopener noreferrer"
            class="font-medium text-signal-info hover:underline">Source ↗</a
          >
        {/if}
      </span>
    </div>
  </article>
{/snippet}

{#if preds.length === 0}
  <div class="card p-8 text-center text-zinc-400">
    <p class="text-sm">No predictions yet.</p>
    <p class="mt-2 text-xs text-zinc-500">
      The ripple tier writes here when a popular stock's high-impact news has a clear read-through to
      other names. It runs inside the regular scan.
    </p>
  </div>
{:else}
  {#if fresh.length > 0}
    <section class="mb-8">
      <h2 class="mb-3 text-sm font-semibold tracking-tight">
        Not yet priced in
        <span class="ml-1 text-xs font-normal text-zinc-500">— still actionable</span>
      </h2>
      <div class="space-y-3">
        {#each fresh as p (p.ticker + p.trigger_ticker)}
          {@render predCard(p)}
        {/each}
      </div>
    </section>
  {/if}

  {#if moving.length > 0}
    <section class="mb-8">
      <h2 class="mb-3 text-sm font-semibold tracking-tight">
        Already moving
        <span class="ml-1 text-xs font-normal text-zinc-500">— read-through confirming</span>
      </h2>
      <div class="space-y-3">
        {#each moving as p (p.ticker + p.trigger_ticker)}
          {@render predCard(p)}
        {/each}
      </div>
    </section>
  {/if}

  {#if contradicted.length > 0}
    <section class="mb-8">
      <h2 class="mb-3 text-sm font-semibold tracking-tight text-zinc-500">
        Tape disagrees
        <span class="ml-1 text-xs font-normal text-zinc-600">— moved against the thesis</span>
      </h2>
      <div class="space-y-3 opacity-70">
        {#each contradicted as p (p.ticker + p.trigger_ticker)}
          {@render predCard(p)}
        {/each}
      </div>
    </section>
  {/if}
{/if}
