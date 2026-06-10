<script lang="ts">
  import type { ScanRow, NewsItem, RankJump } from '$lib/types';
  import { fmtPct, fmtPrice, pctClass, fmtRelative } from '$lib/format';
  import { flagsFor } from '$lib/flags';
  import Sparkline from './Sparkline.svelte';
  import IconCluster from './IconCluster.svelte';

  // Compact, scannable row. Block-char sparkline so it renders without paint
  // cost and stays under control inside the 1fr middle column.
  let {
    row,
    rank,
    isNewEntrant = false,
    isAccel = false,
    pinned = false,
    jump,
    news = [],
    trumpMention = false
  }: {
    row: ScanRow;
    rank?: number;
    isNewEntrant?: boolean;
    isAccel?: boolean;
    pinned?: boolean;
    jump?: RankJump;
    news?: NewsItem[];
    trumpMention?: boolean;
  } = $props();

  const newsHigh = news.some((n) => n.impact === 'high');
  const flags = $derived(flagsFor({ row, isNewEntrant, isAccel, pinned, jump, newsHigh, trumpMention }));

  // "Why" line: synthesis summary if the LLM produced one, otherwise the top
  // headline. Falsy when neither exists so the row stays single-line for the
  // bare technical movers.
  const headline = news[0];
  const why = $derived(row.synthesis?.summary || headline?.title || null);
  const whyMeta = $derived(
    row.synthesis ? 'why' : headline ? fmtRelative(headline.published_at) : null
  );
</script>

<a href={`/t/${row.ticker}`} class="ticker-row text-sm">
  <span class="num text-[10px] text-zinc-500 tabular-nums text-right">
    {rank ?? ''}
  </span>
  <span class="whitespace-nowrap font-semibold tracking-tight text-zinc-100">
    {row.ticker}{#if pinned}<span class="ml-1 text-zinc-500">★</span>{/if}
  </span>
  <span class="spark-cell min-w-0 truncate">
    {#if row.spark && row.spark.length >= 2}
      <Sparkline values={row.spark} up={(row.pct_1d ?? 0) >= 0} treatment="block" />
    {/if}
  </span>
  <span class="num text-xs text-zinc-500 text-right tabular-nums">
    ${fmtPrice(row.price)}
  </span>
  <span class="num text-sm font-semibold text-right tabular-nums {pctClass(row.pct_1d)}">
    {fmtPct(row.pct_1d)}
  </span>
  <IconCluster {flags} max={3} size="sm" />
  {#if why}
    <p class="-mt-1 pl-[84px] sm:pl-[94px] line-clamp-1 text-[11px] leading-relaxed text-zinc-500">
      <span class="text-zinc-600">{whyMeta} ·</span>
      {why}
    </p>
  {/if}
</a>
