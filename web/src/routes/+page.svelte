<script lang="ts">
  import type { ScanRow, NewsItem } from '$lib/types';
  import { fmtPct, fmtPrice, fmtRelVol, fmtClock, fmtRelative, pctClass } from '$lib/format';
  import TickerCard from './TickerCard.svelte';
  import ScanTable from './ScanTable.svelte';
  import StatPill from './StatPill.svelte';

  let { data } = $props();

  const scan = data.scan;
  const news = data.news;
  const deltas = data.deltas;
  const watchlist = data.watchlist?.tickers ?? [];

  const rowsByTicker = new Map<string, ScanRow>(scan?.rows.map((r) => [r.ticker, r]) ?? []);

  const top20 = $derived(
    [...(scan?.rows ?? [])]
      .filter((r) => r.pct_1d != null)
      .sort((a, b) => Math.abs(b.pct_1d!) - Math.abs(a.pct_1d!))
      .slice(0, 20)
  );

  const freshNewsTickers = $derived(() => {
    const top20Set = new Set(top20.map((r) => r.ticker));
    const tickers = Object.entries(news?.ticker_news ?? {})
      .map(([ticker, items]) => ({
        ticker,
        items,
        highImpact: items.some((i) => i.impact === 'high'),
        latest: items.reduce(
          (acc, i) => (i.published_at > acc ? i.published_at : acc),
          items[0]?.published_at ?? ''
        )
      }))
      .filter((x) => !top20Set.has(x.ticker))
      .sort((a, b) => {
        if (a.highImpact !== b.highImpact) return a.highImpact ? -1 : 1;
        return b.latest.localeCompare(a.latest);
      });
    return tickers;
  });

  const watchlistRows = $derived(() => {
    const top20Set = new Set(top20.map((r) => r.ticker));
    const newsSet = new Set(freshNewsTickers().map((x) => x.ticker));
    return watchlist
      .filter((t) => !top20Set.has(t) && !newsSet.has(t))
      .map((t) => ({ ticker: t, row: rowsByTicker.get(t) }))
      .filter((x) => x.row);
  });

  const newEntrants = new Set(deltas?.new_top20_entrants ?? []);
  const accelSet = new Set(deltas?.momentum_accel ?? []);
  const rankJumpMap = new Map(deltas?.rank_jumps?.map((j) => [j.ticker, j]) ?? []);
</script>

<svelte:head>
  <title>Momentum — scan</title>
</svelte:head>

{#if !scan}
  <div class="card p-8 text-center text-zinc-400">
    <p class="text-sm">No scan data yet.</p>
    <p class="mt-2 text-xs">Trigger the GitHub Actions workflow to populate <code>data/scan.json</code>.</p>
  </div>
{:else}
  <section class="mb-6 flex flex-wrap items-center gap-2 text-xs">
    <StatPill label="Window" value={scan.window} accent={scan.window === 'RTH' ? 'up' : 'flat'} />
    <StatPill label="Tickers" value={String(scan.row_count)} accent="info" />
    <StatPill label="Synthesized" value={String(scan.synthesized_count)} accent={scan.synthesized_count > 0 ? 'info' : 'flat'} />
    <StatPill label="Macro events" value={String(news?.macro_events.length ?? 0)} accent={news?.macro_events.length ? 'warn' : 'flat'} />
    <span class="ml-auto text-zinc-500">last scan {fmtRelative(scan.generated_at)} · {fmtClock(scan.generated_at)}</span>
  </section>

  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Top 20 movers</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">by |%chg|</span>
    </header>
    {#if top20.length === 0}
      <p class="text-xs text-zinc-500">No movers in this scan.</p>
    {:else}
      <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each top20 as row, i (row.ticker)}
          <TickerCard
            row={row}
            rank={i + 1}
            isNewEntrant={newEntrants.has(row.ticker)}
            isAccel={accelSet.has(row.ticker)}
            jump={rankJumpMap.get(row.ticker)}
            news={news?.ticker_news[row.ticker] ?? []}
          />
        {/each}
      </div>
    {/if}
  </section>

  {#if freshNewsTickers().length > 0}
    <section class="mb-8">
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">Fresh news</h2>
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">tickers with new headlines</span>
      </header>
      <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each freshNewsTickers().slice(0, 12) as item (item.ticker)}
          {@const row = rowsByTicker.get(item.ticker)}
          {#if row}
            <TickerCard
              row={row}
              isAccel={accelSet.has(row.ticker)}
              news={item.items}
            />
          {/if}
        {/each}
      </div>
    </section>
  {/if}

  {#if watchlistRows().length > 0}
    <section class="mb-8">
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">Watchlist</h2>
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">edit data/watchlist.json</span>
      </header>
      <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each watchlistRows() as { row, ticker } (ticker)}
          {#if row}
            <TickerCard row={row} pinned news={news?.ticker_news[ticker] ?? []} />
          {/if}
        {/each}
      </div>
    </section>
  {/if}

  <section>
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">All scan</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">sortable, searchable</span>
    </header>
    <ScanTable rows={scan.rows} {watchlist} {newEntrants} {accelSet} {rankJumpMap} newsByTicker={news?.ticker_news ?? {}} />
  </section>
{/if}
