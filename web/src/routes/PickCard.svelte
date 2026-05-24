<script lang="ts">
  import type { NewsItem, Recommendation, ScanRow } from '$lib/types';
  import { fmtPct, fmtPrice, pctClass, fmtRelative } from '$lib/format';
  import { flagsFor } from '$lib/flags';
  import Sparkline from './Sparkline.svelte';
  import IconCluster from './IconCluster.svelte';

  let {
    rec,
    row,
    rank,
    news = []
  }: {
    rec: Recommendation;
    row: ScanRow;
    rank: number;
    news?: NewsItem[];
  } = $props();

  const isLong = rec.direction === 'long';
  const synth = row.synthesis;
  const newsHigh = news.some((n) => n.impact === 'high');

  const flags = $derived(flagsFor({ row, newsHigh }));

  // Top headline shown as a one-liner under the synthesis. Dedup by id then
  // pick highest impact / most recent.
  const headlines = [...new Map(news.map((n) => [n.id, n])).values()]
    .sort((a, b) => {
      const impactRank = (n: NewsItem) => (n.impact === 'high' ? 0 : 1);
      return impactRank(a) - impactRank(b) || b.published_at.localeCompare(a.published_at);
    })
    .slice(0, 2);
</script>

<a
  href={`/t/${row.ticker}`}
  class="pick-card row-link {isLong ? 'pick-card-long' : 'pick-card-short'}"
>
  <!-- Row 1: rank / ticker / direction badge -->
  <div class="flex items-baseline justify-between gap-2">
    <div class="flex items-baseline gap-2">
      <span class="num text-[10px] uppercase tracking-wider text-zinc-500">#{rank} pick</span>
    </div>
    <span
      class="rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider {isLong
        ? 'border-signal-up/40 text-signal-up'
        : 'border-signal-down/40 text-signal-down'}"
    >
      {isLong ? '▲ long' : '▼ short'}
    </span>
  </div>

  <!-- Row 2: large ticker -->
  <div class="mt-1 flex items-baseline justify-between gap-3">
    <h3 class="text-3xl font-bold tracking-tight text-zinc-100">{row.ticker}</h3>
    <span class="num text-xs text-zinc-500">${fmtPrice(row.price)}</span>
  </div>

  <!-- Row 3: hero % change (Playfair display) + readable inset sparkline -->
  <div class="mt-2 flex items-end justify-between gap-3">
    <span class="font-display text-4xl font-black leading-none tabular-nums {pctClass(row.pct_1d)}">
      {fmtPct(row.pct_1d)}
    </span>
    {#if row.spark && row.spark.length >= 2}
      <div class="h-9 w-28 shrink-0 opacity-90">
        <Sparkline values={row.spark} up={isLong} height={36} strokeWidth={1.75} />
      </div>
    {/if}
  </div>

  <!-- Row 4: conviction + icon cluster -->
  <div class="mt-3 flex items-center justify-between border-t border-ink-700/60 pt-2.5">
    <div class="flex items-baseline gap-1.5">
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">conviction</span>
      <span class="font-display text-xl font-bold leading-none text-zinc-100 tabular-nums">{rec.score}</span>
    </div>
    <IconCluster {flags} max={3} size="sm" />
  </div>

  <!-- Why -->
  {#if synth?.summary}
    <p class="mt-2.5 line-clamp-2 text-xs leading-relaxed text-zinc-300">
      <span class="text-zinc-500">why:</span>
      {synth.summary}
    </p>
  {/if}

  <!-- Top headlines -->
  {#if headlines.length > 0}
    <ul class="mt-2 space-y-1">
      {#each headlines as item (item.id)}
        <li class="flex items-baseline justify-between gap-2">
          <span class="line-clamp-1 text-[11px] text-zinc-400">
            {#if item.impact === 'high'}<span class="text-signal-warn" title="high impact">●</span> {/if}{item.title}
          </span>
          <span class="num shrink-0 text-[10px] text-zinc-500">{fmtRelative(item.published_at)}</span>
        </li>
      {/each}
    </ul>
  {/if}

  <!-- Reasons (kept as text tags, not pills, so IconCluster owns the visual badge channel) -->
  {#if rec.reasons.length > 0}
    <p class="num mt-2 text-[10px] leading-relaxed text-zinc-500">
      {rec.reasons.slice(0, 4).join(' · ')}
    </p>
  {/if}
</a>
