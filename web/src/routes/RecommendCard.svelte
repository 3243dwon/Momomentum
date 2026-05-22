<script lang="ts">
  import type { NewsItem } from '$lib/types';
  import type { Recommendation } from '$lib/recommend';
  import { fmtPct, fmtPrice, pctClass, fmtRelative } from '$lib/format';
  import Sparkline from './Sparkline.svelte';

  let {
    rec,
    rank,
    news = []
  }: {
    rec: Recommendation;
    rank: number;
    news?: NewsItem[];
  } = $props();

  const row = rec.row;
  const isLong = rec.direction === 'long';
  const synth = row.synthesis;

  // Supporting catalysts: deduped by id (the feed can repeat items),
  // high-impact first, then most recent.
  const headlines = [...new Map(news.map((n) => [n.id, n])).values()]
    .sort((a, b) => {
      const impactRank = (n: NewsItem) => (n.impact === 'high' ? 0 : 1);
      return impactRank(a) - impactRank(b) || b.published_at.localeCompare(a.published_at);
    })
    .slice(0, 3);
</script>

<a href={`/t/${row.ticker}`} class="card row-link p-3">
  <div class="flex items-baseline justify-between gap-2">
    <div class="flex items-baseline gap-1.5">
      <span class="num text-[10px] tabular-nums text-zinc-500">#{rank}</span>
      <span class="text-base font-semibold tracking-tight">{row.ticker}</span>
      <span class={isLong ? 'pill-up' : 'pill-down'}>{isLong ? 'long' : 'short'}</span>
    </div>
    <div class="flex items-baseline gap-2">
      <span class="num text-xs text-zinc-500">${fmtPrice(row.price)}</span>
      <span class="num text-sm font-semibold {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</span>
    </div>
  </div>

  {#if row.spark && row.spark.length >= 2}
    <div class="mt-2">
      <Sparkline values={row.spark} up={isLong} />
    </div>
  {/if}

  <div class="mt-2 flex flex-wrap items-center gap-1">
    <span class="num mr-0.5 text-[10px] text-zinc-500" title="momentum score">score {rec.score}</span>
    {#each rec.reasons.slice(0, 5) as reason}
      <span class="pill-flat">{reason}</span>
    {/each}
    {#each rec.cautions as caution}
      <span class="pill-warn">{caution}</span>
    {/each}
  </div>

  {#if synth?.summary}
    <p class="mt-3 line-clamp-2 text-xs leading-relaxed text-zinc-300">
      <span class="text-zinc-500">why:</span>
      {synth.summary}
    </p>
  {/if}

  {#if headlines.length > 0}
    <div class="mt-2.5 border-t border-ink-700/60 pt-2">
      <div class="mb-1 text-[10px] uppercase tracking-wider text-zinc-500">news</div>
      <ul class="space-y-1">
        {#each headlines as item (item.id)}
          <li class="flex items-baseline justify-between gap-2">
            <span class="line-clamp-1 text-xs text-zinc-400">
              {#if item.impact === 'high'}<span class="text-signal-warn" title="high impact">●</span> {/if}{item.title}
            </span>
            <span class="num shrink-0 text-[10px] text-zinc-500">{fmtRelative(item.published_at)}</span>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</a>
