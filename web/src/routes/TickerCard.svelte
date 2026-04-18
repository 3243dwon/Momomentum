<script lang="ts">
  import type { ScanRow, NewsItem, RankJump } from '$lib/types';
  import { fmtPct, fmtPrice, fmtRelVol, pctClass, fmtRelative } from '$lib/format';

  let {
    row,
    rank,
    isNewEntrant = false,
    isAccel = false,
    pinned = false,
    jump,
    news = []
  }: {
    row: ScanRow;
    rank?: number;
    isNewEntrant?: boolean;
    isAccel?: boolean;
    pinned?: boolean;
    jump?: RankJump;
    news?: NewsItem[];
  } = $props();

  const synth = row.synthesis;
  const headlineNews = news.slice(0, 1)[0];
</script>

<a href={`/t/${row.ticker}`} class="card row-link p-3">
  <div class="flex items-baseline justify-between gap-2">
    <div class="flex items-baseline gap-1.5">
      {#if rank}
        <span class="num text-[10px] tabular-nums text-zinc-500">#{rank}</span>
      {/if}
      <span class="text-base font-semibold tracking-tight">{row.ticker}</span>
      {#if pinned}
        <span class="text-zinc-500" title="watchlist">★</span>
      {/if}
    </div>
    <div class="flex items-baseline gap-2">
      <span class="num text-xs text-zinc-500">${fmtPrice(row.price)}</span>
      <span class="num text-sm font-semibold {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</span>
    </div>
  </div>

  <div class="mt-2 flex flex-wrap items-center gap-1 text-[10px] text-zinc-500">
    {#if row.rel_volume}
      <span>vol {fmtRelVol(row.rel_volume)}</span>
    {/if}
    {#if row.rsi_14 != null}
      <span>·</span>
      <span>RSI {row.rsi_14.toFixed(0)}</span>
    {/if}
    {#if row.macd_cross === 'bullish'}
      <span>·</span><span class="text-signal-up">MACD↑</span>
    {:else if row.macd_cross === 'bearish'}
      <span>·</span><span class="text-signal-down">MACD↓</span>
    {/if}
    {#if row.snapshot?.gap_pct != null}
      <span>·</span>
      <span>gap {fmtPct(row.snapshot.gap_pct)}</span>
    {/if}
    {#if row.intraday?.above_vwap != null}
      <span>·</span>
      <span class={row.intraday.above_vwap ? 'text-signal-up' : 'text-signal-down'}>
        {row.intraday.above_vwap ? '>VWAP' : '<VWAP'}
      </span>
    {/if}
  </div>

  <div class="mt-2 flex flex-wrap gap-1">
    {#if row.tier === 'mega'}<span class="pill-flat">mega</span>{:else if row.tier === 'large'}<span class="pill-flat">large</span>{:else if row.tier === 'midsmall'}<span class="pill-flat">mid/small</span>{/if}
    {#if isNewEntrant}<span class="pill-info">new top-20</span>{/if}
    {#if jump}<span class="pill-info">↑{jump.delta} ranks</span>{/if}
    {#if isAccel}<span class="pill-warn">accel</span>{/if}
    {#each row.flags.filter((f) => f === 'unusual_volume') as flag}<span class="pill-warn">vol</span>{/each}
    {#each row.flags.filter((f) => f === 'overbought' || f === 'oversold') as flag}
      <span class="pill-flat">{flag}</span>
    {/each}
  </div>

  {#if synth?.summary}
    <p class="mt-3 line-clamp-3 text-xs leading-relaxed text-zinc-300">
      <span class="text-zinc-500">why:</span>
      {synth.summary}
    </p>
  {:else if headlineNews}
    <p class="mt-3 line-clamp-2 text-xs leading-relaxed text-zinc-400">
      <span class="text-zinc-500">{fmtRelative(headlineNews.published_at)} ·</span>
      {headlineNews.title}
    </p>
  {/if}
</a>
