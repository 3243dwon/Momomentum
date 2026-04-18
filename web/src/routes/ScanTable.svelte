<script lang="ts">
  import type { ScanRow, NewsItem, RankJump } from '$lib/types';
  import { fmtPct, fmtPrice, fmtRelVol, fmtVolume, pctClass } from '$lib/format';

  type Props = {
    rows: ScanRow[];
    watchlist: string[];
    newEntrants: Set<string>;
    accelSet: Set<string>;
    rankJumpMap: Map<string, RankJump>;
    newsByTicker: Record<string, NewsItem[]>;
  };

  let { rows, watchlist, newEntrants, accelSet, rankJumpMap, newsByTicker }: Props = $props();

  type SortKey = 'ticker' | 'price' | 'pct_1d' | 'pct_5d' | 'rel_volume' | 'rsi_14' | 'volume';
  let sortKey = $state<SortKey>('pct_1d');
  let sortDir = $state<'asc' | 'desc'>('desc');
  let query = $state('');

  const watchSet = new Set(watchlist);

  function setSort(k: SortKey) {
    if (sortKey === k) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      sortKey = k;
      sortDir = k === 'ticker' ? 'asc' : 'desc';
    }
  }

  function compareNum(a: number | null, b: number | null, dir: 'asc' | 'desc') {
    const av = a ?? -Infinity;
    const bv = b ?? -Infinity;
    return dir === 'asc' ? av - bv : bv - av;
  }

  const sorted = $derived.by(() => {
    const q = query.trim().toUpperCase();
    let r = q ? rows.filter((x) => x.ticker.includes(q)) : rows;
    return [...r].sort((a, b) => {
      if (sortKey === 'ticker') {
        return sortDir === 'asc'
          ? a.ticker.localeCompare(b.ticker)
          : b.ticker.localeCompare(a.ticker);
      }
      if (sortKey === 'pct_1d') return compareNum(a.pct_1d != null ? Math.abs(a.pct_1d) : null, b.pct_1d != null ? Math.abs(b.pct_1d) : null, sortDir);
      return compareNum(
        (a as any)[sortKey] ?? null,
        (b as any)[sortKey] ?? null,
        sortDir
      );
    });
  });

  const visible = $derived.by(() => sorted.slice(0, 250));
  const sortIndicator = (k: SortKey) => (sortKey === k ? (sortDir === 'asc' ? '▲' : '▼') : '');
</script>

<div class="card">
  <div class="flex flex-wrap items-center gap-3 border-b border-ink-700 px-3 py-2">
    <input
      type="search"
      placeholder="filter ticker…"
      bind:value={query}
      class="num w-32 rounded bg-ink-800 px-2 py-1 text-xs uppercase placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-signal-info"
    />
    <span class="text-[10px] uppercase tracking-wider text-zinc-500">
      showing {Math.min(visible.length, 250)} of {sorted.length}
    </span>
  </div>

  <div class="hidden overflow-x-auto md:block">
    <table class="w-full text-xs">
      <thead class="sticky top-0 bg-ink-900 text-[10px] uppercase tracking-wider text-zinc-500">
        <tr class="border-b border-ink-700">
          <th class="cursor-pointer px-3 py-2 text-left" onclick={() => setSort('ticker')}>Ticker {sortIndicator('ticker')}</th>
          <th class="cursor-pointer px-3 py-2 text-right" onclick={() => setSort('price')}>Price {sortIndicator('price')}</th>
          <th class="cursor-pointer px-3 py-2 text-right" onclick={() => setSort('pct_1d')}>%chg 1d {sortIndicator('pct_1d')}</th>
          <th class="cursor-pointer px-3 py-2 text-right" onclick={() => setSort('pct_5d')}>%chg 5d {sortIndicator('pct_5d')}</th>
          <th class="cursor-pointer px-3 py-2 text-right" onclick={() => setSort('rel_volume')}>RelVol {sortIndicator('rel_volume')}</th>
          <th class="cursor-pointer px-3 py-2 text-right" onclick={() => setSort('volume')}>Volume {sortIndicator('volume')}</th>
          <th class="cursor-pointer px-3 py-2 text-right" onclick={() => setSort('rsi_14')}>RSI {sortIndicator('rsi_14')}</th>
          <th class="px-3 py-2 text-left">Flags</th>
        </tr>
      </thead>
      <tbody>
        {#each visible as row (row.ticker)}
          <tr class="border-b border-ink-700/40 hover:bg-ink-800/40">
            <td class="px-3 py-1.5">
              <a href={`/t/${row.ticker}`} class="font-semibold hover:text-signal-info">
                {row.ticker}
                {#if watchSet.has(row.ticker)}<span class="ml-1 text-zinc-500">★</span>{/if}
              </a>
            </td>
            <td class="num px-3 py-1.5 text-right text-zinc-300">${fmtPrice(row.price)}</td>
            <td class="num px-3 py-1.5 text-right {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</td>
            <td class="num px-3 py-1.5 text-right {pctClass(row.pct_5d)}">{fmtPct(row.pct_5d)}</td>
            <td class="num px-3 py-1.5 text-right text-zinc-400">{fmtRelVol(row.rel_volume)}</td>
            <td class="num px-3 py-1.5 text-right text-zinc-500">{fmtVolume(row.volume)}</td>
            <td class="num px-3 py-1.5 text-right text-zinc-400">{row.rsi_14 ?? '–'}</td>
            <td class="px-3 py-1.5">
              <div class="flex flex-wrap gap-1">
                {#if newEntrants.has(row.ticker)}<span class="pill-info">new</span>{/if}
                {#if accelSet.has(row.ticker)}<span class="pill-warn">accel</span>{/if}
                {#if rankJumpMap.has(row.ticker)}<span class="pill-info">↑rank</span>{/if}
                {#if (newsByTicker[row.ticker]?.length ?? 0) > 0}<span class="pill-info">news</span>{/if}
                {#if row.macd_cross === 'bullish'}<span class="pill-up">macd↑</span>{/if}
                {#if row.macd_cross === 'bearish'}<span class="pill-down">macd↓</span>{/if}
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <div class="divide-y divide-ink-700/40 md:hidden">
    {#each visible as row (row.ticker)}
      <a href={`/t/${row.ticker}`} class="row-link flex items-center justify-between gap-2 px-3 py-2">
        <div class="flex flex-col">
          <span class="text-sm font-semibold">{row.ticker}{#if watchSet.has(row.ticker)}<span class="ml-1 text-zinc-500">★</span>{/if}</span>
          <span class="text-[10px] text-zinc-500">${fmtPrice(row.price)} · vol {fmtRelVol(row.rel_volume)}</span>
        </div>
        <div class="flex items-baseline gap-2">
          <span class="num text-sm font-semibold {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</span>
          {#if (newsByTicker[row.ticker]?.length ?? 0) > 0}<span class="pill-info">news</span>{/if}
        </div>
      </a>
    {/each}
  </div>
</div>
