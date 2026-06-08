<script lang="ts">
  import type { ScanRow, NewsItem } from '$lib/types';
  import { fmtPct, fmtPrice, fmtRelVol, fmtClock, fmtRelative, pctClass } from '$lib/format';
  import TickerCard from './TickerCard.svelte';
  import TickerRow from './TickerRow.svelte';
  import PickCard from './PickCard.svelte';
  import ScanTable from './ScanTable.svelte';
  import StatPill from './StatPill.svelte';
  import FilterBar, { type Filters } from './FilterBar.svelte';

  let { data } = $props();

  const scan = data.scan;
  const news = data.news;
  const deltas = data.deltas;
  const watchlist = data.watchlist?.tickers ?? [];

  // Tickers Trump mentioned on Truth Social recently — used to light up the
  // TRUMP chip on any pick/row/card whose ticker he named. Rare overlap, but
  // when a mover is something he just posted about, that's worth flagging.
  const trumpMentions = new Set(data.pulse?.tickers_mentioned ?? []);

  const rowsByTicker = new Map<string, ScanRow>(scan?.rows.map((r) => [r.ticker, r]) ?? []);
  const newsCountByTicker = new Map<string, number>(
    Object.entries(news?.ticker_news ?? {}).map(([t, items]) => [t, items.length])
  );

  // Serenity — latest posts surfaced on the dashboard (full feed at /serenity).
  const serenityTop = (data.serenity?.tweets ?? []).slice(0, 3);
  const SERENITY_HOT = 3.0;
  function serenityLive(ticker: string) {
    const r = rowsByTicker.get(ticker);
    if (!r || r.pct_1d == null) return undefined;
    return { pct: r.pct_1d, moving: Math.abs(r.pct_1d) >= SERENITY_HOT };
  }
  const SERENITY_STANCE: Record<string, string> = {
    bull: 'text-signal-up',
    bear: 'text-signal-down',
    neutral: 'text-zinc-400'
  };

  // Ripple predictions — the freshest forward calls (names predicted to move on
  // ANOTHER company's news, before they've priced it in). Full list at /predictions.
  const freshPredictions = (data.predictions?.predictions ?? [])
    .filter((p) => p.priced_in === 'no')
    .slice(0, 4);

  let filters = $state<Filters>({
    size: 'any',
    move: 'any',
    volume: 'any',
    news: 'any',
    vwap: 'any'
  });

  const filteredRows = $derived.by(() => {
    if (!scan) return [];
    return scan.rows.filter((r) => {
      if (filters.size === 'large' && r.tier !== 'mega' && r.tier !== 'large') return false;
      if (filters.size === 'midsmall' && r.tier !== 'midsmall') return false;
      if (filters.move === 'p3' && (r.pct_1d == null || Math.abs(r.pct_1d) < 3)) return false;
      if (filters.move === 'p5' && (r.pct_1d == null || Math.abs(r.pct_1d) < 5)) return false;
      if (filters.volume === 'unusual' && (r.rel_volume == null || r.rel_volume < 2)) return false;
      if (filters.news === 'with' && !((newsCountByTicker.get(r.ticker) ?? 0) > 0)) return false;
      if (filters.vwap === 'above' && r.intraday?.above_vwap !== true) return false;
      return true;
    });
  });

  // Picks are computed by the backend (scanner/recommend.py) and shipped in
  // scan.json. Bucket them by horizon — catalyst-backed = a thesis to hold
  // beyond the next tick; technical = a price-action trade. Direction (long
  // vs short bet) is shown per-card via the badge. Picks for tickers the
  // filter excludes are dropped; within each bucket we sort by score.
  const recommended = $derived.by(() => {
    const recs = scan?.recommendations;
    if (!recs) return { longTerm: [], shortTerm: [] };
    const visible = new Set(filteredRows.map((r) => r.ticker));
    const all = [...recs.longs, ...recs.shorts]
      .filter((r) => visible.has(r.ticker))
      .sort((a, b) => b.score - a.score);
    return {
      longTerm: all.filter((r) => (r.horizon ?? 'short') === 'long'),
      shortTerm: all.filter((r) => (r.horizon ?? 'short') === 'short')
    };
  });

  const top20 = $derived.by(() =>
    [...filteredRows]
      .filter((r) => r.pct_1d != null)
      .sort((a, b) => Math.abs(b.pct_1d!) - Math.abs(a.pct_1d!))
      .slice(0, 20)
  );

  const freshNewsTickers = $derived.by(() => {
    const top20Set = new Set(top20.map((r) => r.ticker));
    const filteredSet = new Set(filteredRows.map((r) => r.ticker));
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
      .filter((x) => !top20Set.has(x.ticker) && filteredSet.has(x.ticker))
      .sort((a, b) => {
        if (a.highImpact !== b.highImpact) return a.highImpact ? -1 : 1;
        return b.latest.localeCompare(a.latest);
      });
    return tickers;
  });

  const watchlistRows = $derived.by(() => {
    const top20Set = new Set(top20.map((r) => r.ticker));
    const newsSet = new Set(freshNewsTickers.map((x) => x.ticker));
    return watchlist
      .filter((t) => !top20Set.has(t) && !newsSet.has(t))
      .map((t) => ({ ticker: t, row: rowsByTicker.get(t) }));
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
  <section class="mb-3 flex flex-wrap items-center gap-2 text-xs">
    <StatPill label="Window" value={scan.window} accent={scan.window === 'RTH' ? 'up' : 'flat'} />
    <StatPill label="Tickers" value={`${filteredRows.length}/${scan.row_count}`} accent="info" />
    <StatPill label="Synthesized" value={String(scan.synthesized_count)} accent={scan.synthesized_count > 0 ? 'info' : 'flat'} />
    <StatPill label="Macro events" value={String(news?.macro_events.length ?? 0)} accent={news?.macro_events.length ? 'warn' : 'flat'} />
    <span class="ml-auto text-zinc-500">last scan {fmtRelative(scan.generated_at)} · {fmtClock(scan.generated_at)}</span>
  </section>

  <FilterBar bind:filters />

  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Recommended</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">momentum setups with confirmation</span>
    </header>
    {#if recommended.longTerm.length === 0 && recommended.shortTerm.length === 0}
      <div class="card p-6 text-center text-xs text-zinc-500">
        <p>No high-conviction setups this scan.</p>
        <p class="mt-1">Fresh picks land here after the next refresh — usually within an hour.</p>
      </div>
    {:else}
      {#if recommended.longTerm.length > 0}
        <h3 class="mb-2 flex flex-wrap items-baseline gap-x-2 text-[10px] font-semibold uppercase tracking-wider text-signal-info">
          Long-term picks
          <span class="font-normal normal-case tracking-normal text-zinc-500">catalyst-backed · news explains the move</span>
        </h3>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {#each recommended.longTerm as rec, i (rec.ticker)}
            {@const row = rowsByTicker.get(rec.ticker)}
            {#if row}
              <PickCard {rec} {row} rank={i + 1} news={news?.ticker_news[rec.ticker] ?? []} trumpMention={trumpMentions.has(rec.ticker)} />
            {/if}
          {/each}
        </div>
      {/if}
      {#if recommended.shortTerm.length > 0}
        <h3 class="mb-2 mt-4 flex flex-wrap items-baseline gap-x-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-300">
          Short-term picks
          <span class="font-normal normal-case tracking-normal text-zinc-500">pure technical · price-action trade</span>
        </h3>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {#each recommended.shortTerm as rec, i (rec.ticker)}
            {@const row = rowsByTicker.get(rec.ticker)}
            {#if row}
              <PickCard {rec} {row} rank={i + 1} news={news?.ticker_news[rec.ticker] ?? []} trumpMention={trumpMentions.has(rec.ticker)} />
            {/if}
          {/each}
        </div>
      {/if}
    {/if}
  </section>

  {#if freshPredictions.length > 0}
    <section class="mb-8">
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">🔮 Ahead of the move</h2>
        <a href="/predictions" class="text-[10px] uppercase tracking-wider text-signal-info hover:underline">View all →</a>
      </header>
      <div class="grid gap-3 sm:grid-cols-2">
        {#each freshPredictions as p (p.ticker + p.trigger_ticker)}
          {@const dir = p.direction === 'bullish' ? 'text-signal-up' : 'text-signal-down'}
          <article class="card p-3">
            <div class="mb-1.5 flex items-center justify-between gap-2">
              <div class="flex flex-wrap items-center gap-1.5">
                <a href={`/t/${p.ticker}`} class="font-mono text-xs font-semibold hover:underline {dir}">${p.ticker}</a>
                <span class="text-[10px] font-medium {dir}">{p.direction === 'bullish' ? '📈 beneficiary' : '📉 at risk'}</span>
              </div>
              <span class="whitespace-nowrap rounded bg-signal-info/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-signal-info">not yet priced in</span>
            </div>
            <p class="line-clamp-2 text-xs leading-relaxed text-zinc-300">{p.rationale}</p>
            <p class="mt-1.5 text-[10px] text-zinc-500">via <a href={`/t/${p.trigger_ticker}`} class="font-mono text-zinc-400 hover:underline">${p.trigger_ticker}</a> · conf {p.confidence} · {p.horizon}</p>
          </article>
        {/each}
      </div>
    </section>
  {/if}

  {#if serenityTop.length > 0}
    <section class="mb-8">
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">🧠 Serenity</h2>
        <a href="/serenity" class="text-[10px] uppercase tracking-wider text-signal-info hover:underline">View all →</a>
      </header>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {#each serenityTop as t (t.id)}
          <article class="card p-3">
            <div class="mb-1.5 flex items-center justify-between gap-2">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="text-[10px] font-semibold uppercase tracking-wider {SERENITY_STANCE[t.stance] ?? 'text-zinc-400'}">{t.stance}</span>
                {#each t.tickers as tk}
                  {@const lv = serenityLive(tk)}
                  <a href={`/t/${tk}`} class="font-mono text-xs hover:underline {lv?.moving ? pctClass(lv.pct) : 'text-zinc-300'}">${tk}{#if lv?.moving}<span class="ml-0.5">{fmtPct(lv.pct)}</span>{/if}</a>
                {/each}
              </div>
              <span class="whitespace-nowrap text-[10px] text-zinc-500">{fmtRelative(t.createdAt)}</span>
            </div>
            <p class="line-clamp-3 text-xs leading-relaxed text-zinc-300">{t.summaryEn || t.text}</p>
            <a href={t.url} target="_blank" rel="noopener noreferrer" class="mt-2 inline-block text-[10px] font-medium text-signal-info hover:underline">View on X ↗</a>
          </article>
        {/each}
      </div>
    </section>
  {/if}

  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Top 20 movers</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">by |%chg|</span>
    </header>
    {#if top20.length === 0}
      <p class="text-xs text-zinc-500">No movers in this scan.</p>
    {:else}
      <div class="card overflow-hidden">
        {#each top20 as row, i (row.ticker)}
          <TickerRow
            row={row}
            rank={i + 1}
            isNewEntrant={newEntrants.has(row.ticker)}
            isAccel={accelSet.has(row.ticker)}
            jump={rankJumpMap.get(row.ticker)}
            news={news?.ticker_news[row.ticker] ?? []}
            trumpMention={trumpMentions.has(row.ticker)}
          />
        {/each}
      </div>
    {/if}
  </section>

  {#if freshNewsTickers.length > 0}
    <section class="mb-8">
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">Fresh news</h2>
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">tickers with new headlines</span>
      </header>
      <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each freshNewsTickers.slice(0, 12) as item (item.ticker)}
          {@const row = rowsByTicker.get(item.ticker)}
          {#if row}
            <TickerCard
              row={row}
              isAccel={accelSet.has(row.ticker)}
              news={item.items}
              trumpMention={trumpMentions.has(row.ticker)}
            />
          {/if}
        {/each}
      </div>
    </section>
  {/if}

  {#if watchlistRows.length > 0}
    <details open class="mb-8 group">
      <summary class="mb-3 flex cursor-pointer list-none items-center justify-between select-none">
        <h2 class="text-sm font-semibold tracking-tight">
          <span class="inline-block w-3 text-zinc-500 transition-transform group-open:rotate-90">▸</span>
          Watchlist
          <span class="ml-1 text-[10px] font-normal text-zinc-500">
            ({watchlistRows.length})
          </span>
        </h2>
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">
          {watchlistRows.map(({ ticker }) => ticker).join(' · ')}
        </span>
      </summary>
      <div class="card overflow-hidden">
        {#each watchlistRows as { row, ticker } (ticker)}
          {#if row}
            <TickerRow row={row} pinned news={news?.ticker_news[ticker] ?? []} trumpMention={trumpMentions.has(ticker)} />
          {:else}
            <a href={`/t/${ticker}`} class="ticker-row text-sm opacity-60">
              <span></span>
              <span class="font-semibold tracking-tight">{ticker} <span class="text-zinc-500">★</span></span>
              <span class="text-[10px] uppercase tracking-wider text-zinc-500 col-span-4">
                awaiting next scan
              </span>
            </a>
          {/if}
        {/each}
      </div>
    </details>
  {/if}

  <details class="group">
    <summary class="mb-3 flex cursor-pointer list-none items-center justify-between select-none">
      <h2 class="text-sm font-semibold tracking-tight">
        <span class="inline-block w-3 text-zinc-500 transition-transform group-open:rotate-90">▸</span>
        All scan
        <span class="ml-1 text-[10px] font-normal text-zinc-500">
          ({filteredRows.length})
        </span>
      </h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">sortable, searchable</span>
    </summary>
    <ScanTable rows={filteredRows} {watchlist} {newEntrants} {accelSet} {rankJumpMap} newsByTicker={news?.ticker_news ?? {}} />
  </details>
{/if}
