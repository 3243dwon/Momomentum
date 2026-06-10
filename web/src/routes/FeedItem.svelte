<script lang="ts">
  import type { FeedItem } from '$lib/feed';
  import { KIND_META } from '$lib/feed';
  import type { ScanRow } from '$lib/types';
  import { fmtPct, fmtRelative, pctClass } from '$lib/format';

  let {
    item,
    rowsByTicker,
    trust
  }: {
    item: FeedItem;
    rowsByTicker?: Map<string, ScanRow>;
    /** Optional one-line track-record warning (e.g. for serenity items). */
    trust?: string | null;
  } = $props();

  const stanceClass: Record<string, string> = {
    bull: 'text-signal-up',
    bear: 'text-signal-down',
    neutral: 'text-zinc-400'
  };

  function live(ticker: string) {
    const r = rowsByTicker?.get(ticker);
    if (!r || r.pct_1d == null) return null;
    return r.pct_1d;
  }
</script>

<article class="flex gap-2.5 border-b border-ink-700/60 px-3 py-2.5 last:border-b-0">
  <span class="mt-0.5 h-fit whitespace-nowrap rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider {KIND_META[item.kind].chip}">
    {KIND_META[item.kind].label}
  </span>
  <div class="min-w-0 flex-1">
    <div class="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
      {#if item.stance}
        <span class="text-[10px] font-semibold uppercase tracking-wider {stanceClass[item.stance]}">{item.stance}</span>
      {/if}
      {#each item.tickers.slice(0, 4) as tk (tk)}
        {@const pct = live(tk)}
        <a href={`/t/${tk}`} class="num text-xs font-semibold hover:underline {pct != null && Math.abs(pct) >= 3 ? pctClass(pct) : 'text-zinc-200'}">
          ${tk}{#if pct != null && Math.abs(pct) >= 3}<span class="ml-0.5 font-normal">{fmtPct(pct)}</span>{/if}
        </a>
      {/each}
      {#if item.via}
        <span class="text-[10px] text-zinc-500">via <a href={`/t/${item.via}`} class="num text-zinc-400 hover:underline">${item.via}</a></span>
      {/if}
      {#if item.badge}
        <span class="rounded bg-signal-info/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-signal-info">{item.badge}</span>
      {/if}
      <span class="ml-auto whitespace-nowrap text-[10px] text-zinc-500">{fmtRelative(item.ts)}</span>
    </div>
    <p class="mt-0.5 line-clamp-2 text-xs leading-relaxed text-zinc-300">{item.title}</p>
    {#if item.detail && item.detail !== item.title}
      <p class="mt-0.5 line-clamp-1 text-[11px] text-zinc-500">{item.detail}</p>
    {/if}
    <div class="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-zinc-500">
      {#if item.confidence}<span>conf {item.confidence}</span>{/if}
      {#if item.horizon}<span>{item.horizon}</span>{/if}
      {#if item.url}
        <a href={item.url} target="_blank" rel="noopener noreferrer" class="text-signal-info hover:underline">source ↗</a>
      {/if}
      {#if trust}
        <span class="text-signal-down">{trust}</span>
      {/if}
    </div>
  </div>
</article>
