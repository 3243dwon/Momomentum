<script lang="ts">
  import type { ScanRow } from '$lib/types';
  import { fmtPct, fmtPrice, fmtClock, pctClass } from '$lib/format';
  import { buildFeed, KIND_META, type FeedKind } from '$lib/feed';
  import { signalTrust, scoreInverted } from '$lib/trust';
  import { now, staleness, STALE_CLASS, fmtAge } from '$lib/freshness';
  import { invalidateAll } from '$app/navigation';
  import { browser } from '$app/environment';
  import { prefersReducedMotion } from '$lib/scrub.svelte';
  import ColdOpen from './ColdOpen.svelte';
  import TickerRow from './TickerRow.svelte';
  import TakeCard from './TakeCard.svelte';
  import ScanTable from './ScanTable.svelte';
  import StatPill from './StatPill.svelte';
  import FilterBar, { type Filters } from './FilterBar.svelte';
  import FeedItem from './FeedItem.svelte';

  let { data } = $props();

  // Cold open: the funnel intro plays once per browser session, is always
  // skippable, and never renders for reduced-motion users.
  let showIntro = $state(
    browser &&
      !prefersReducedMotion() &&
      (() => {
        try {
          return !sessionStorage.getItem('momentum:seen-intro');
        } catch {
          return false;
        }
      })()
  );

  const scan = $derived(data.scan);
  const news = $derived(data.news);
  const deltas = $derived(data.deltas);
  const watchlist = $derived(data.watchlist?.tickers ?? []);
  const briefing = $derived(data.briefing);

  // Tickers Trump mentioned on Truth Social recently — used to light up the
  // TRUMP chip on any pick/row/card whose ticker he named.
  const trumpMentions = $derived(new Set(data.pulse?.tickers_mentioned ?? []));

  const rowsByTicker = $derived(
    new Map<string, ScanRow>(scan?.rows.map((r) => [r.ticker, r]) ?? [])
  );

  // --- Freshness: the label ticks, colors by age, and the pill is a refresh
  // button. The layout's scan-watch auto-invalidates when a new scan lands.
  const scanAge = $derived(staleness(scan?.generated_at, $now));
  let refreshing = $state(false);
  async function refresh() {
    refreshing = true;
    await invalidateAll();
    refreshing = false;
  }

  // --- Briefing: render only while it plausibly describes the current scan.
  // A briefing much older than the scan means the writer failed — hide it
  // rather than narrate yesterday as today.
  const briefingFresh = $derived.by(() => {
    if (!briefing?.generated_at || !scan?.generated_at) return false;
    const b = new Date(briefing.generated_at).getTime();
    const s = new Date(scan.generated_at).getTime();
    return s - b < 6 * 3600_000 && $now - b < 36 * 3600_000;
  });

  // --- Desk takes: only decision=take renders as a card. Passes collapse to
  // one line — four 500px "don't trade this" cards was the old layout's
  // biggest lie. Desk-less picks (desk failed soft) still show as takes.
  const allRecs = $derived.by(() => {
    const recs = scan?.recommendations;
    if (!recs) return [];
    return [...recs.longs, ...recs.shorts].sort((a, b) => b.score - a.score);
  });
  const takes = $derived(allRecs.filter((r) => !r.desk || r.desk.decision === 'take'));
  const passes = $derived(allRecs.filter((r) => r.desk && r.desk.decision !== 'take'));
  const invertedScore = $derived(scoreInverted(data.recPerf, 'long'));

  // --- Top movers: ALWAYS unfiltered. Curated sections are not query results;
  // the filter bar lives with the all-scan table it actually describes.
  const top20 = $derived.by(() =>
    [...(scan?.rows ?? [])]
      .filter((r) => r.pct_1d != null)
      .sort((a, b) => Math.abs(b.pct_1d!) - Math.abs(a.pct_1d!))
      .slice(0, 20)
  );

  // --- Unified feed: news, Serenity, predictions, macro, Trump — one stream.
  const feedAll = $derived(
    buildFeed({
      news,
      serenity: data.serenity,
      predictions: data.predictions,
      pulse: data.pulse,
      limit: 60
    })
  );
  let activeKinds = $state<Set<FeedKind>>(new Set());
  function toggleKind(k: FeedKind) {
    const next = new Set(activeKinds);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    activeKinds = next;
  }
  const feed = $derived(
    (activeKinds.size === 0 ? feedAll : feedAll.filter((i) => activeKinds.has(i.kind))).slice(0, 20)
  );
  const presentKinds = $derived.by(() => {
    const ks = new Set(feedAll.map((i) => i.kind));
    return (Object.keys(KIND_META) as FeedKind[]).filter((k) => ks.has(k));
  });

  // Serenity's track record rides along on its feed items — the signal class
  // is graded where the calls appear, not on a stats page nobody visits.
  const serenityTrust = $derived(signalTrust(data.performance, 'serenity_match'));
  const serenityWarning = $derived(
    serenityTrust?.grade === 'noise' ? `signal class: ${serenityTrust.label}` : null
  );

  const watchlistRows = $derived(
    watchlist.map((t) => ({ ticker: t, row: rowsByTicker.get(t) }))
  );

  let filters = $state<Filters>({
    size: 'any',
    move: 'any',
    volume: 'any',
    news: 'any',
    vwap: 'any'
  });

  const newsCountByTicker = $derived(
    new Map<string, number>(
      Object.entries(news?.ticker_news ?? {}).map(([t, items]) => [t, items.length])
    )
  );

  // Filters scope ONLY the all-scan table below.
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

  const newEntrants = $derived(new Set(deltas?.new_top20_entrants ?? []));
  const accelSet = $derived(new Set(deltas?.momentum_accel ?? []));
  const rankJumpMap = $derived(new Map(deltas?.rank_jumps?.map((j) => [j.ticker, j]) ?? []));

  const REGIME_META: Record<string, { label: string; cls: 'up' | 'down' | 'warn' }> = {
    risk_on: { label: 'risk on', cls: 'up' },
    risk_off: { label: 'risk off', cls: 'down' },
    mixed: { label: 'mixed', cls: 'warn' }
  };
  const regime = $derived(scan?.regime?.label ? REGIME_META[scan.regime.label] : null);
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
  {#if showIntro}
    <!-- Cold open: 5,370 -> today's scan, played as the front door. -->
    <ColdOpen
      {scan}
      headline={briefingFresh ? (briefing?.headline ?? null) : null}
      dismiss={() => (showIntro = false)}
    />
  {/if}

  <!-- Status strip: window · regime · freshness. The freshness label ticks and
       is tappable to refetch — no more frozen "23m ago" lying all afternoon. -->
  <section class="mb-4 flex flex-wrap items-center gap-2 text-xs">
    <StatPill label="Window" value={scan.window} accent={scan.window === 'RTH' ? 'up' : 'flat'} />
    {#if regime}
      <StatPill label="Regime" value={regime.label} accent={regime.cls} />
    {/if}
    <StatPill label="Tickers" value={String(scan.row_count)} accent="info" />
    {#if news?.macro_events.length}
      <StatPill label="Macro events" value={String(news.macro_events.length)} accent="warn" />
    {/if}
    <button
      type="button"
      onclick={refresh}
      title={`scan at ${fmtClock(scan.generated_at)} — tap to refresh`}
      class="ml-auto flex items-center gap-1.5 rounded px-2 py-1 transition-colors hover:bg-ink-800 {STALE_CLASS[scanAge.level]}"
    >
      <span class="relative flex h-1.5 w-1.5">
        {#if scanAge.level === 'fresh'}
          <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60"></span>
        {/if}
        <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-current"></span>
      </span>
      <span class="{refreshing ? 'animate-pulse' : ''}">scan {fmtAge(scanAge.ageMin)}</span>
    </button>
  </section>

  {#if briefing && briefingFresh}
    <section class="card mb-8 border-signal-info/30 p-4">
      <header class="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-sm font-semibold tracking-tight">Briefing</h2>
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">{briefing.window} · one read per scan</span>
      </header>
      <!-- The machine's voice: same serif the cold open climaxes in, so the
           intro hands off into the page instead of switching worlds. -->
      <p class="font-display text-xl font-black leading-snug text-zinc-100 sm:text-2xl">{briefing.headline}</p>
      {#if briefing.market_state?.line}
        <p class="mt-1.5 text-xs leading-relaxed text-zinc-400">{briefing.market_state.line}</p>
      {/if}
      {#if briefing.actions?.length}
        <div class="mt-3 space-y-1.5">
          {#each briefing.actions as a (a.ticker)}
            <a href={`/t/${a.ticker}`} class="flex flex-wrap items-baseline gap-x-2 text-xs hover:bg-ink-800/40 rounded px-1 -mx-1 py-0.5">
              <span class="num font-semibold {a.direction === 'long' ? 'text-signal-up' : 'text-signal-down'}">{a.direction === 'long' ? '▲' : '▼'} {a.ticker}</span>
              {#if a.entry != null}
                <span class="num text-zinc-400">{fmtPrice(a.entry)} → <span class="text-signal-up">{fmtPrice(a.target)}</span> / stop <span class="text-signal-down">{fmtPrice(a.stop)}</span></span>
              {/if}
              <span class="text-zinc-300">{a.line}</span>
            </a>
          {/each}
        </div>
      {/if}
      {#if briefing.watch?.length}
        <p class="mt-2.5 text-xs leading-relaxed text-zinc-400">
          <span class="text-[10px] uppercase tracking-wider text-zinc-500">watch · </span>
          {#each briefing.watch as w, i (w.ticker + w.type)}
            <a href={`/t/${w.ticker}`} class="num text-zinc-300 hover:underline">${w.ticker}</a><span class="text-zinc-500"> {w.line}{i < briefing.watch.length - 1 ? ' · ' : ''}</span>
          {/each}
        </p>
      {/if}
      {#if briefing.changed?.length}
        <p class="mt-1.5 text-[11px] text-zinc-500">since last scan: {briefing.changed.join(' · ')}</p>
      {/if}
      {#if briefing.caveats?.length}
        <p class="mt-1.5 text-[10px] text-zinc-600">{briefing.caveats.join(' · ')}</p>
      {/if}
    </section>
  {/if}

  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Top movers</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">by |%chg| · unfiltered</span>
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

  <section class="mb-8">
    <header class="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 class="text-sm font-semibold tracking-tight">Desk takes</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">
        {takes.length} take{takes.length === 1 ? '' : 's'} · {passes.length} passed
      </span>
    </header>
    {#if invertedScore}
      <p class="mb-2 rounded border border-signal-warn/30 bg-signal-warn/10 px-3 py-1.5 text-[11px] text-signal-warn">
        Calibration warning: low-score longs are currently outperforming high-score longs over 5d — treat the conviction number as decoration until this flips. Details on <a href="/review" class="underline">Review</a>.
      </p>
    {/if}
    {#if takes.length === 0}
      <div class="card p-5 text-center text-xs text-zinc-500">
        <p>The desk took nothing this scan{passes.length ? ` — it passed on ${passes.map((p) => p.ticker).join(', ')}` : ''}.</p>
      </div>
    {:else}
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {#each takes as rec (rec.ticker + rec.direction)}
          {@const row = rowsByTicker.get(rec.ticker)}
          {#if row}
            <TakeCard {rec} {row} recPerf={data.recPerf} />
          {/if}
        {/each}
      </div>
    {/if}
    {#if passes.length > 0 && takes.length > 0}
      <details class="group mt-2">
        <summary class="cursor-pointer list-none text-[11px] text-zinc-500 hover:text-zinc-300">
          <span class="inline-block w-3 transition-transform group-open:rotate-90">▸</span>
          Desk passed on {passes.map((p) => p.ticker).join(', ')} — why
        </summary>
        <div class="card mt-2 divide-y divide-ink-700/60">
          {#each passes as p (p.ticker + p.direction)}
            <div class="px-3 py-2 text-xs">
              <a href={`/t/${p.ticker}`} class="num font-semibold text-zinc-200 hover:underline">{p.ticker}</a>
              <span class="ml-1.5 text-[10px] uppercase tracking-wider text-zinc-500">{p.direction} · score {p.score}</span>
              <p class="mt-0.5 leading-relaxed text-zinc-400">{p.desk?.rationale ?? p.desk?.risk?.concern ?? 'no rationale recorded'}</p>
            </div>
          {/each}
        </div>
      </details>
    {/if}
  </section>

  {#if feedAll.length > 0}
    <section class="mb-8">
      <header class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-semibold tracking-tight">Feed</h2>
        <div class="flex flex-wrap items-center gap-1">
          {#each presentKinds as k (k)}
            <button
              type="button"
              onclick={() => toggleKind(k)}
              class="rounded px-2 py-0.5 text-[10px] uppercase tracking-wider transition-colors {activeKinds.size === 0 || activeKinds.has(k)
                ? KIND_META[k].chip
                : 'text-zinc-600 hover:text-zinc-400'}"
            >
              {KIND_META[k].label}
            </button>
          {/each}
        </div>
      </header>
      {#if serenityWarning && feed.some((i) => i.kind === 'serenity')}
        <p class="mb-2 text-[10px] text-signal-down">
          🧠 Serenity {serenityWarning} — read for context, not for trades. <a href="/review" class="underline">track record</a>
        </p>
      {/if}
      <div class="card overflow-hidden">
        {#each feed as item (item.id)}
          <FeedItem {item} {rowsByTicker} />
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
        <span class="hidden text-[10px] uppercase tracking-wider text-zinc-500 sm:block">
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
              <span class="col-span-2 text-[10px] uppercase tracking-wider text-zinc-500">
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
          ({filteredRows.length}/{scan.row_count})
        </span>
      </h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">sortable · filterable</span>
    </summary>
    <FilterBar bind:filters />
    <ScanTable rows={filteredRows} {watchlist} {newEntrants} {accelSet} {rankJumpMap} newsByTicker={news?.ticker_news ?? {}} />
  </details>
{/if}
