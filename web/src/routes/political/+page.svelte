<script lang="ts">
  import { fmtRelative } from '$lib/format';
  import type { PoliticalTrade } from '$lib/types';

  let { data } = $props();
  const political = data.political;
  const scan = data.scan;
  const watchlist = new Set(data.watchlist?.tickers ?? []);

  // Cross-reference: which disclosed-trade tickers are also in today's scan?
  // Boldfaced cross-references are the actionable signal — politicians' trades
  // matter most when they overlap with your existing universe / watchlist.
  const movingTickers = new Set(
    (scan?.rows ?? []).filter((r) => r.pct_1d != null && Math.abs(r.pct_1d) >= 3).map((r) => r.ticker)
  );

  // Sort tickers by relevance: watchlist > moving > buy count > total count.
  // Within a chamber and side, the most recent filings first.
  type TickerBucket = {
    ticker: string;
    trades: PoliticalTrade[];
    buys: number;
    sells: number;
    politicians: Set<string>;
  };

  function bucketize(trades: PoliticalTrade[]): TickerBucket[] {
    const map = new Map<string, TickerBucket>();
    for (const t of trades) {
      if (!t.ticker) continue;
      let b = map.get(t.ticker);
      if (!b) {
        b = { ticker: t.ticker, trades: [], buys: 0, sells: 0, politicians: new Set() };
        map.set(t.ticker, b);
      }
      b.trades.push(t);
      if (t.side === 'buy') b.buys++;
      else if (t.side === 'sell') b.sells++;
      if (t.politician) b.politicians.add(t.politician);
    }
    return [...map.values()].sort((a, b) => {
      const aw = watchlist.has(a.ticker) ? 100 : 0;
      const bw = watchlist.has(b.ticker) ? 100 : 0;
      const am = movingTickers.has(a.ticker) ? 50 : 0;
      const bm = movingTickers.has(b.ticker) ? 50 : 0;
      return bw + bm + b.trades.length - (aw + am + a.trades.length);
    });
  }

  const buckets = $derived(bucketize(political?.trades ?? []));

  // Side filter chip-state — simple in-memory, no persistence.
  let sideFilter = $state<'all' | 'buy' | 'sell'>('all');
  let chamberFilter = $state<'all' | 'senate' | 'house'>('all');

  const filteredBuckets = $derived(
    buckets
      .map((b) => ({
        ...b,
        trades: b.trades.filter(
          (t) =>
            (sideFilter === 'all' || t.side === sideFilter) &&
            (chamberFilter === 'all' || t.chamber === chamberFilter)
        )
      }))
      .filter((b) => b.trades.length > 0)
  );

  function sideClass(side: string): string {
    if (side === 'buy') return 'text-signal-up';
    if (side === 'sell') return 'text-signal-down';
    return 'text-zinc-500';
  }
  function sideLabel(side: string): string {
    if (side === 'buy') return 'BUY';
    if (side === 'sell') return 'SELL';
    if (side === 'exchange') return 'EXCH';
    return side.toUpperCase();
  }
</script>

<svelte:head>
  <title>Momentum — political</title>
</svelte:head>

{#if !political || political.status === 'no_key'}
  <div class="card p-6 text-sm leading-relaxed">
    <h2 class="text-base font-semibold tracking-tight">Political trades — not configured</h2>
    <p class="mt-3 text-zinc-400">
      This page shows recently-disclosed stock trades by US Senators and House members,
      pulled from <a href="https://financialmodelingprep.com" class="underline">Financial Modeling Prep</a>'s
      free tier (250 requests/day, no payment).
    </p>
    <ol class="mt-3 list-decimal space-y-1 pl-5 text-zinc-400">
      <li>Sign up at financialmodelingprep.com and copy your API key.</li>
      <li>Add <code class="text-zinc-200">FMP_API_KEY=...</code> to your <code class="text-zinc-200">.env</code>.</li>
      <li>The next scan run will populate <code class="text-zinc-200">data/political.json</code>.</li>
    </ol>
    <p class="mt-3 text-xs text-zinc-500">
      Cabinet members file under the OGE Form 278e system, which isn't in any free aggregator
      and is out of scope for v1.
    </p>
  </div>
{:else if political.status === 'empty' || political.total_trades === 0}
  <div class="card p-6 text-sm">
    <h2 class="text-base font-semibold tracking-tight">No recent political trades</h2>
    <p class="mt-2 text-zinc-400">
      The {political.window_days}-day window had no disclosed Congress trades that survived normalization.
      Last refresh: {fmtRelative(political.generated_at)}.
    </p>
  </div>
{:else}
  <section class="mb-3 flex flex-wrap items-center gap-2 text-xs">
    <span class="rounded bg-ink-800 px-2 py-0.5 text-zinc-300">
      {political.total_trades} trades
    </span>
    <span class="rounded bg-ink-800 px-2 py-0.5 text-zinc-300">
      {political.unique_tickers} tickers
    </span>
    <span class="rounded bg-ink-800 px-2 py-0.5 text-zinc-400">
      {political.window_days}d window
    </span>
    <span class="ml-auto text-zinc-500">refreshed {fmtRelative(political.generated_at)}</span>
  </section>

  <section class="card mb-4 flex flex-wrap items-center gap-2 p-2 text-[10px] uppercase tracking-wider">
    <span class="px-1 text-zinc-500">Side</span>
    <div class="flex gap-1">
      {#each [{ v: 'all', l: 'All' }, { v: 'buy', l: 'Buys' }, { v: 'sell', l: 'Sells' }] as o}
        <button
          type="button"
          onclick={() => (sideFilter = o.v as any)}
          class="rounded px-2 py-1 transition-colors {sideFilter === o.v
            ? 'bg-signal-info/15 text-signal-info'
            : 'text-zinc-400 hover:bg-ink-800'}"
        >
          {o.l}
        </button>
      {/each}
    </div>
    <span class="ml-3 px-1 text-zinc-500">Chamber</span>
    <div class="flex gap-1">
      {#each [{ v: 'all', l: 'All' }, { v: 'senate', l: 'Senate' }, { v: 'house', l: 'House' }] as o}
        <button
          type="button"
          onclick={() => (chamberFilter = o.v as any)}
          class="rounded px-2 py-1 transition-colors {chamberFilter === o.v
            ? 'bg-signal-info/15 text-signal-info'
            : 'text-zinc-400 hover:bg-ink-800'}"
        >
          {o.l}
        </button>
      {/each}
    </div>
  </section>

  {#if filteredBuckets.length === 0}
    <p class="text-xs text-zinc-500">No trades match the current filter.</p>
  {:else}
    <div class="space-y-3">
      {#each filteredBuckets as b (b.ticker)}
        {@const isWatched = watchlist.has(b.ticker)}
        {@const isMoving = movingTickers.has(b.ticker)}
        <div class="card p-3">
          <header class="flex flex-wrap items-baseline justify-between gap-2">
            <div class="flex items-baseline gap-2">
              <a href={`/t/${b.ticker}`} class="text-base font-bold tracking-tight hover:underline">
                {b.ticker}
              </a>
              {#if isWatched}<span class="text-zinc-500" title="on watchlist">★</span>{/if}
              {#if isMoving}<span class="rounded bg-signal-warn/15 px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider text-signal-warn">MOVING TODAY</span>{/if}
              <span class="text-[11px] text-zinc-500">
                {b.trades.length} trade{b.trades.length === 1 ? '' : 's'} ·
                {b.politicians.size} politician{b.politicians.size === 1 ? '' : 's'}
              </span>
            </div>
            <div class="num flex gap-2 text-[11px]">
              {#if b.buys > 0}<span class="text-signal-up">{b.buys} buy{b.buys === 1 ? '' : 's'}</span>{/if}
              {#if b.sells > 0}<span class="text-signal-down">{b.sells} sell{b.sells === 1 ? '' : 's'}</span>{/if}
            </div>
          </header>

          <ul class="mt-2 divide-y divide-ink-700/40 text-sm">
            {#each b.trades as t}
              <li class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5">
                <span class="font-mono text-[10px] uppercase tracking-wider {sideClass(t.side)}">
                  {sideLabel(t.side)}
                </span>
                <span class="text-zinc-200">{t.politician ?? '—'}</span>
                <span class="text-[10px] uppercase tracking-wider text-zinc-500">{t.chamber}</span>
                {#if t.amount_band}
                  <span class="num text-[11px] text-zinc-400">{t.amount_band}</span>
                {/if}
                <span class="ml-auto text-[10px] text-zinc-500">
                  {#if t.transaction_date}traded {t.transaction_date}{/if}
                  {#if t.filed_at} · filed {fmtRelative(t.filed_at)}{/if}
                </span>
                {#if t.link}
                  <a href={t.link} target="_blank" rel="noopener" class="text-[10px] text-zinc-500 hover:text-zinc-300">PTR ↗</a>
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/each}
    </div>
  {/if}

  <p class="mt-6 text-[10px] uppercase tracking-wider text-zinc-500">
    Source: {political.source ?? 'FMP'} · House &amp; Senate disclosed trades only ·
    Cabinet members (OGE 278e) not currently covered.
  </p>
{/if}
