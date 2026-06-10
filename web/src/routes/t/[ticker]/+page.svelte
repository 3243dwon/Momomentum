<script lang="ts">
  import { fmtPct, fmtPrice, fmtRelVol, fmtVolume, pctClass, fmtRelative, impactPill, confidencePill } from '$lib/format';
  import { readsFor, type ReadTone } from '$lib/reads';
  import { flagsFor } from '$lib/flags';
  import { computeLevels, quickPlan } from '$lib/levels';
  import { KIND_META } from '$lib/feed';
  import { now, staleness, fmtAge, STALE_CLASS } from '$lib/freshness';
  import type { PricedIn, LedgerStatus, WeeklyClassification, WeeklyPrediction } from '$lib/types';
  import Sparkline from '../../Sparkline.svelte';
  import PriceChart from '../../PriceChart.svelte';
  import IconCluster from '../../IconCluster.svelte';

  let { data } = $props();

  // Everything derives from `data` (not destructured consts) so cross-links
  // between /t/ pages — this page links to trigger/target tickers — re-render
  // when SvelteKit reuses the component with fresh load data.
  const ticker = $derived(data.ticker);
  const row = $derived(data.row);
  const scan = $derived(data.scan);
  const news = $derived(data.news);
  const macroMentions = $derived(data.macroMentions);
  const predictionsAbout = $derived(data.predictionsAbout);
  const predictionsFrom = $derived(data.predictionsFrom);
  const feed = $derived(data.feed);
  const weeklyEntry = $derived(data.weeklyEntry);
  const congressTrades = $derived(data.congressTrades);
  const ledgerEntries = $derived(data.ledgerEntries);

  const PRICED: Record<PricedIn, string> = {
    no: 'not yet priced in',
    partial: 'started moving',
    yes: 'already moved',
    contradicted: 'tape disagrees'
  };

  const reads = $derived(row ? readsFor(row) : []);
  const dotCls: Record<ReadTone, string> = {
    up: 'bg-signal-up',
    down: 'bg-signal-down',
    warn: 'bg-signal-warn',
    flat: 'bg-zinc-500'
  };
  const textCls: Record<ReadTone, string> = {
    up: 'text-signal-up',
    down: 'text-signal-down',
    warn: 'text-signal-warn',
    flat: 'text-zinc-400'
  };

  // "data as of" ticks with the shared 30s clock so it never freezes stale.
  const stale = $derived(staleness(scan?.generated_at, $now));

  // Flag chips via the shared FLAG_META vocabulary (label + tooltip), same as
  // the home rows/cards — not raw scanner strings.
  const newsHigh = $derived(news.some((n) => n.impact === 'high'));
  const trumpMention = $derived((data.pulse?.tickers_mentioned ?? []).includes(ticker));
  const flags = $derived(row ? flagsFor({ row, newsHigh, trumpMention }) : []);

  // Heuristic levels (client-side fallback, same math the PickCards use).
  // Side follows the tape: momentum up → long structure, down → short.
  const levelSide = $derived((row?.pct_1d ?? row?.pct_5d ?? 0) >= 0 ? ('long' as const) : ('short' as const));
  const levels = $derived(row ? computeLevels(row, levelSide) : null);

  // Enrich feed news items with their publisher from the full NewsItem.
  const newsById = $derived(new Map(news.map((n) => [`news:${n.id}`, n])));

  const STANCE_CLASS: Record<string, string> = {
    bull: 'text-signal-up',
    bear: 'text-signal-down',
    neutral: 'text-zinc-400'
  };

  function classBadge(c: WeeklyClassification): string {
    switch (c) {
      case 'real_momentum':
        return 'pill-up';
      case 'fakeout':
        return 'pill-down';
      default:
        return 'pill-flat';
    }
  }
  function predBadge(p: WeeklyPrediction): string {
    switch (p) {
      case 'continuation':
        return 'pill-up';
      case 'reversal':
        return 'pill-down';
      default:
        return 'pill-flat';
    }
  }

  const STATUS_PILL: Record<LedgerStatus, string> = {
    pending: 'pill-flat',
    hit: 'pill-up',
    miss: 'pill-down',
    untracked: 'pill-warn'
  };
  const HORIZONS = ['1d', '3d', '5d'] as const;

  function sidePill(side: string): string {
    if (side === 'buy') return 'pill-up';
    if (side === 'sell') return 'pill-down';
    return 'pill-flat';
  }
</script>

<svelte:head>
  <title>{ticker} — Momentum</title>
</svelte:head>

<div class="mb-4 flex items-center gap-2 text-xs text-zinc-500">
  <a href="/" class="hover:text-zinc-300">← scan</a>
  <span>/</span>
  <span class="text-zinc-300">{ticker}</span>
</div>

<!-- Header: always renders — every alert links here, including tickers the
     scan doesn't cover. Each section below is independent of the scan row. -->
<section class="card mb-8 p-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="min-w-0">
      <h1 class="text-2xl font-semibold tracking-tight">{ticker}</h1>
      {#if row}
        <p class="text-xs text-zinc-500">last price ${fmtPrice(row.price)}</p>
      {/if}
      {#if scan}
        <p class="mt-0.5 text-[10px] uppercase tracking-wider {STALE_CLASS[stale.level]}">
          data as of {fmtAge(stale.ageMin)}
        </p>
      {/if}
    </div>
    {#if row}
      <div class="flex items-center gap-4">
        {#if row.spark && row.spark.length >= 2}
          <div class="h-8 w-28 shrink-0 opacity-90">
            <Sparkline values={row.spark} height={32} strokeWidth={1.75} />
          </div>
        {/if}
        <div class="text-right">
          <div class="text-[10px] uppercase tracking-wider text-zinc-500">1-day</div>
          <div class="num text-lg font-semibold {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</div>
        </div>
        <div class="text-right">
          <div class="text-[10px] uppercase tracking-wider text-zinc-500">5-day</div>
          <div class="num text-lg font-semibold {pctClass(row.pct_5d)}">{fmtPct(row.pct_5d)}</div>
        </div>
      </div>
    {/if}
  </div>

  {#if !row}
    <p class="mt-3 text-xs text-zinc-500">
      not in the current scan — showing everything else we know
    </p>
  {:else}
    <div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500">Volume</div>
        <div class="num text-sm">{fmtVolume(row.volume)}</div>
      </div>
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500">Avg vol (20d)</div>
        <div class="num text-sm">{fmtVolume(row.avg_volume_20d)}</div>
      </div>
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500">Rel volume</div>
        <div class="num text-sm">{fmtRelVol(row.rel_volume)}</div>
      </div>
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500">RSI 14</div>
        <div class="num text-sm">{row.rsi_14 ?? '–'}</div>
      </div>
    </div>

    {#if flags.length}
      <div class="mt-4">
        <IconCluster {flags} max={12} size="md" />
      </div>
    {/if}

    {#if row.caution_level}
      <div class="mt-4 rounded border {row.caution_level === 'stretched' ? 'border-signal-down/30 bg-signal-down/5' : 'border-signal-warn/30 bg-signal-warn/5'} p-3">
        <div class="mb-1 flex items-center gap-2">
          <span class="text-sm font-semibold {row.caution_level === 'stretched' ? 'text-signal-down' : 'text-signal-warn'}">
            {row.caution_level === 'stretched' ? '⛔ Late-entry risk high' : '⚠️ Move extended'}
          </span>
        </div>
        <p class="text-xs text-zinc-400">
          Momentum scanners lag by 15–30 minutes. By the time you see a move, it may already be topping.
          The following signals suggest this one might be played out:
        </p>
        <ul class="mt-2 space-y-0.5 text-xs text-zinc-300">
          {#each row.caution_reasons ?? [] as reason}
            <li>· {reason}</li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}
</section>

<!-- Synthesis: the "why" sits right under the header so the answer comes first -->
{#if row?.synthesis}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Why it moved</h2>
      <div class="flex items-center gap-2 text-[10px] uppercase tracking-wider">
        <span class="pill {confidencePill(row.synthesis.confidence)}">conf · {row.synthesis.confidence}</span>
        <span class="pill-flat">{row.synthesis.verdict.replace(/_/g, ' ')}</span>
      </div>
    </header>
    <div class="card p-4">
      <p class="text-sm leading-relaxed text-zinc-200">{row.synthesis.summary}</p>
    </div>
  </section>
{/if}

<!-- Trade levels: same heuristic + visual language as the home PickCards -->
{#if row && levels}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Trade levels</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">heuristic · not advice</span>
    </header>
    <div class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">
          {levels.side} · {levels.pivotLabel} ${fmtPrice(levels.pivot)}
        </span>
        {#if levels.rr != null}
          <span
            class="num text-[10px] font-semibold {levels.rr >= 2 ? 'text-signal-up' : 'text-zinc-400'}"
            title="reward : risk"
          >{levels.rr.toFixed(1)}R</span>
        {/if}
      </div>
      {#if row.spark && row.spark.length >= 2}
        <div class="mb-3">
          <PriceChart values={row.spark} {levels} intraday={row.intraday ?? null} up={(row.pct_1d ?? 0) >= 0} />
          <p class="mt-1 text-right text-[9px] uppercase tracking-wider text-zinc-600">20-day closes · levels overlaid</p>
        </div>
      {/if}
      <div class="grid grid-cols-3 gap-1 text-center">
        <div>
          <div class="text-[9px] uppercase tracking-wider text-zinc-500">entry</div>
          <div class="num text-xs font-semibold text-zinc-100">${fmtPrice(levels.entry)}</div>
        </div>
        <div>
          <div class="text-[9px] uppercase tracking-wider text-zinc-500">stop</div>
          <div class="num text-xs font-semibold text-signal-down">${fmtPrice(levels.stop)}</div>
        </div>
        <div>
          <div class="text-[9px] uppercase tracking-wider text-zinc-500">target</div>
          <div class="num text-xs font-semibold text-signal-up">${fmtPrice(levels.target)}</div>
        </div>
      </div>
      <p class="mt-3 border-t border-ink-700/50 pt-2 text-xs leading-relaxed text-zinc-300">
        {quickPlan(levels)}
      </p>
    </div>
  </section>
{/if}

<!-- 指标解读 — live indicator reads (degrades gracefully outside a session) -->
{#if reads.length}
  <section class="card mb-8 p-4">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">指标解读 · What the signals say</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">live read</span>
    </header>
    <ul class="divide-y divide-ink-700/50">
      {#each reads as r (r.key)}
        <li class="flex items-start gap-3 py-2">
          <span class="mt-[6px] h-2 w-2 shrink-0 rounded-full {dotCls[r.tone]}"></span>
          <span class="w-[4.5rem] shrink-0 text-xs font-medium leading-relaxed text-zinc-400">{r.name}</span>
          <span class="num w-20 shrink-0 text-sm leading-relaxed text-zinc-200">{r.value}</span>
          <span class="flex-1 text-xs leading-relaxed {textCls[r.tone]}">{r.verdict}</span>
        </li>
      {/each}
    </ul>
    <p class="mt-3 border-t border-ink-700/50 pt-2 text-[10px] leading-relaxed text-zinc-500">
      🟢 偏多 · 🔴 偏空 · 🟡 当心 · ⚪ 中性。想知道每个指标怎么用?
      <a href="/learn" class="text-signal-info hover:underline">看指标解读 →</a>
    </p>
  </section>
{/if}

{#if row && (row.snapshot || row.intraday)}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Intraday signals</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">pro-grade indicators</span>
    </header>
    <div class="card p-4">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {#if row.snapshot?.gap_pct != null}
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">Gap (vs prev close)</div>
            <div class="num text-sm {pctClass(row.snapshot.gap_pct)}">{fmtPct(row.snapshot.gap_pct)}</div>
          </div>
        {/if}
        {#if row.snapshot?.live_price != null}
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">Live price</div>
            <div class="num text-sm">${fmtPrice(row.snapshot.live_price)}</div>
          </div>
        {/if}
        {#if row.intraday?.vwap != null}
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">VWAP</div>
            <div class="num text-sm">${fmtPrice(row.intraday.vwap)}</div>
          </div>
        {/if}
        {#if row.intraday?.above_vwap != null}
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">Trend</div>
            <div class="text-sm font-medium {row.intraday.above_vwap ? 'text-signal-up' : 'text-signal-down'}">
              {row.intraday.above_vwap ? '↑ above VWAP' : '↓ below VWAP'}
            </div>
          </div>
        {/if}
        {#if row.intraday?.hod != null}
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">High of day</div>
            <div class="num text-sm">${fmtPrice(row.intraday.hod)}</div>
          </div>
        {/if}
        {#if row.intraday?.lod != null}
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">Low of day</div>
            <div class="num text-sm">${fmtPrice(row.intraday.lod)}</div>
          </div>
        {/if}
      </div>
      {#if row.intraday}
        <p class="mt-3 text-[10px] text-zinc-500">From {row.intraday.bars} 5-min bars today (IEX feed).</p>
      {/if}
    </div>
  </section>
{/if}

<!-- Ripple tier: calls about this name + calls this name triggered -->
{#if predictionsAbout.length > 0 || predictionsFrom.length > 0}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">🔮 Catalyst calls on {ticker}</h2>
      <a href="/predictions" class="text-[10px] uppercase tracking-wider text-signal-info hover:underline">All →</a>
    </header>
    <div class="card p-4">
      {#if predictionsAbout.length > 0}
        <div class="space-y-3">
          {#each predictionsAbout as p (p.trigger_ticker + p.event_summary)}
            {@const dir = p.direction === 'bullish' ? 'text-signal-up' : 'text-signal-down'}
            <div class="border-l-2 pl-3 {p.direction === 'bullish' ? 'border-signal-up/40' : 'border-signal-down/40'}">
              <div class="mb-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider">
                <span class="text-xs font-medium normal-case {dir}">{p.direction === 'bullish' ? '📈 likely beneficiary' : '📉 likely at risk'}</span>
                <span class="rounded px-1.5 py-0.5 {p.priced_in === 'no' ? 'bg-signal-info/15 text-signal-info' : 'text-zinc-500'}">{PRICED[p.priced_in]}</span>
                <span class="pill-flat">conf {p.confidence}</span>
                <span class="pill-flat">{p.horizon}</span>
                {#if p.created_at}<span class="normal-case text-zinc-500">called {fmtRelative(p.created_at)}</span>{/if}
              </div>
              <p class="text-sm leading-relaxed text-zinc-200">{p.rationale}</p>
              <p class="mt-1 text-[11px] text-zinc-500">
                via <a href={`/t/${p.trigger_ticker}`} class="font-mono text-zinc-300 hover:underline">${p.trigger_ticker}</a> — {p.event_summary}{#if p.news_url} · <a href={p.news_url} target="_blank" rel="noopener noreferrer" class="text-signal-info hover:underline">source ↗</a>{/if}
              </p>
            </div>
          {/each}
        </div>
      {/if}

      {#if predictionsFrom.length > 0}
        <div class={predictionsAbout.length > 0 ? 'mt-4 border-t border-ink-700/50 pt-4' : ''}>
          <h3 class="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            this name as trigger — its news is rippling to
          </h3>
          <div class="space-y-3">
            {#each predictionsFrom as p (p.ticker + p.event_summary)}
              {@const dir = p.direction === 'bullish' ? 'text-signal-up' : 'text-signal-down'}
              <div class="border-l-2 pl-3 {p.direction === 'bullish' ? 'border-signal-up/40' : 'border-signal-down/40'}">
                <div class="mb-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider">
                  <a href={`/t/${p.ticker}`} class="font-mono text-xs font-semibold normal-case hover:underline {dir}">${p.ticker}</a>
                  <span class="text-xs font-medium normal-case {dir}">{p.direction === 'bullish' ? '📈 beneficiary' : '📉 at risk'}</span>
                  <span class="rounded px-1.5 py-0.5 {p.priced_in === 'no' ? 'bg-signal-info/15 text-signal-info' : 'text-zinc-500'}">{PRICED[p.priced_in]}</span>
                  <span class="pill-flat">conf {p.confidence}</span>
                  <span class="pill-flat">{p.horizon}</span>
                  {#if p.created_at}<span class="normal-case text-zinc-500">called {fmtRelative(p.created_at)}</span>{/if}
                </div>
                <p class="text-sm leading-relaxed text-zinc-200">{p.rationale}</p>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  </section>
{/if}

<!-- Unified feed: news + Serenity + Trump mentions, newest first -->
{#if feed.length > 0}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">In the feed</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">news · serenity · trump</span>
    </header>
    <ul class="card divide-y divide-ink-700/60">
      {#each feed as item (item.id)}
        {@const meta = KIND_META[item.kind]}
        {@const src = newsById.get(item.id)}
        <li class="px-4 py-3">
          <div class="mb-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500">
            <span class="rounded px-1.5 py-0.5 text-[9px] {meta.chip}">{meta.label}</span>
            {#if item.stance}
              <span class="font-semibold {STANCE_CLASS[item.stance] ?? 'text-zinc-400'}">{item.stance}</span>
            {/if}
            {#if item.impact}<span class="pill {impactPill(item.impact)}">{item.impact}</span>{/if}
            {#if src}<span>{src.publisher || src.source}</span>{/if}
            <span>{fmtRelative(item.ts)}</span>
          </div>
          {#if item.url}
            <a href={item.url} target="_blank" rel="noopener noreferrer" class="text-sm leading-snug text-zinc-200 hover:text-signal-info">
              {item.title} <span class="text-[10px] text-zinc-500">↗</span>
            </a>
          {:else}
            <p class="text-sm leading-snug text-zinc-200">{item.title}</p>
          {/if}
        </li>
      {/each}
    </ul>
  </section>
{/if}

{#if macroMentions.length > 0}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Macro context</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">events naming {ticker}</span>
    </header>
    <ul class="card divide-y divide-ink-700/60">
      {#each macroMentions as event}
        {@const asBeneficiary = event.beneficiaries.find((b) => b.ticker.toUpperCase() === ticker)}
        {@const asLoser = event.losers.find((l) => l.ticker.toUpperCase() === ticker)}
        <li class="px-4 py-3">
          <p class="mb-1 text-xs text-zinc-400">{event.event_summary}</p>
          {#if asBeneficiary}
            <p class="text-sm text-signal-up">
              <span class="text-[10px] uppercase tracking-wider text-zinc-500">beneficiary · {asBeneficiary.confidence} · {asBeneficiary.horizon}</span><br />
              {asBeneficiary.rationale}
            </p>
          {/if}
          {#if asLoser}
            <p class="text-sm text-signal-down">
              <span class="text-[10px] uppercase tracking-wider text-zinc-500">loser · {asLoser.confidence} · {asLoser.horizon}</span><br />
              {asLoser.rationale}
            </p>
          {/if}
        </li>
      {/each}
    </ul>
  </section>
{/if}

<!-- Last weekly verdict -->
{#if weeklyEntry}
  {@const analysis = weeklyEntry.analysis}
  {@const cls = analysis?.classification ?? weeklyEntry.heuristic_classification}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Last weekly verdict</h2>
      <a href="/weekly" class="text-[10px] uppercase tracking-wider text-signal-info hover:underline">
        {data.weekEnding ? `week ending ${data.weekEnding} →` : 'All →'}
      </a>
    </header>
    <div class="card p-4">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <span class="pill {classBadge(cls)}">{cls.replace('_', ' ')}</span>
        {#if analysis}
          <span class="pill {predBadge(analysis.prediction)}">{analysis.prediction}</span>
          <span class="pill {confidencePill(analysis.prediction_confidence)}">conf · {analysis.prediction_confidence}</span>
        {/if}
        <span class="ml-auto text-xs">
          <span class="text-zinc-500">week</span>
          <span class="num font-medium {pctClass(weeklyEntry.metrics.week_return_pct)}">{fmtPct(weeklyEntry.metrics.week_return_pct)}</span>
        </span>
      </div>
      {#if analysis?.classification_reasoning}
        <p class="mb-2 text-sm leading-relaxed text-zinc-300">
          <span class="text-[10px] uppercase tracking-wider text-zinc-500">what happened: </span>
          {analysis.classification_reasoning}
        </p>
      {/if}
      {#if analysis?.prediction_rationale}
        <p class="text-sm leading-relaxed text-zinc-300">
          <span class="text-[10px] uppercase tracking-wider text-zinc-500">next 1-4 weeks: </span>
          {analysis.prediction_rationale}
        </p>
      {/if}
    </div>
  </section>
{/if}

<!-- Congressional trading disclosures on this name -->
{#if congressTrades.length > 0}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Congress activity</h2>
      <a href="/political" class="text-[10px] uppercase tracking-wider text-signal-info hover:underline">All →</a>
    </header>
    <ul class="card divide-y divide-ink-700/60">
      {#each congressTrades as t}
        <li class="px-4 py-3">
          <div class="flex flex-wrap items-center gap-2 text-xs">
            <span class="font-medium text-zinc-200">{t.politician ?? 'Unknown'}</span>
            <span class="pill-flat">{t.chamber}</span>
            <span class="pill {sidePill(t.side)}">{t.side}</span>
            {#if t.amount_band}<span class="num text-zinc-400">{t.amount_band}</span>{/if}
          </div>
          <div class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] uppercase tracking-wider text-zinc-500">
            {#if t.transaction_date}<span>traded {t.transaction_date}</span>{/if}
            {#if t.filed_at}<span>filed {t.filed_at}</span>{/if}
            {#if t.link}
              <a href={t.link} target="_blank" rel="noopener noreferrer" class="normal-case text-signal-info hover:underline">filing ↗</a>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<!-- Accountability ledger: every call we've made on this name + how it went -->
{#if ledgerEntries && ledgerEntries.length > 0}
  <section class="mb-8">
    <header class="mb-3 flex items-center justify-between">
      <h2 class="text-sm font-semibold tracking-tight">Past calls on this name</h2>
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">accountability ledger</span>
    </header>
    <ul class="card divide-y divide-ink-700/60">
      {#each ledgerEntries as e (e.id)}
        <li class="px-4 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="pill-flat">{e.type.replace(/_/g, ' ')}</span>
            {#if e.direction}
              <span class="text-[10px] font-medium uppercase tracking-wider {e.direction === 'long' ? 'text-signal-up' : 'text-signal-down'}">
                {e.direction === 'long' ? '▲ long' : '▼ short'}
              </span>
            {/if}
            <span class="pill {STATUS_PILL[e.status]}">{e.status}</span>
            <span class="ml-auto text-[10px] text-zinc-500">{fmtRelative(e.ts)}</span>
          </div>
          {#if e.thesis}
            <p class="mt-1 line-clamp-2 text-xs leading-relaxed text-zinc-400">{e.thesis}</p>
          {/if}
          <div class="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-0.5 text-[11px]">
            {#if e.price != null}
              <span class="text-zinc-500">at <span class="num text-zinc-300">${fmtPrice(e.price)}</span></span>
            {/if}
            {#each HORIZONS as h}
              <span class="text-zinc-500">{h}
                <span class="num {pctClass(e.outcomes[h])}">{e.outcomes[h] == null ? '–' : fmtPct(e.outcomes[h])}</span>
              </span>
            {/each}
          </div>
        </li>
      {/each}
    </ul>
  </section>
{/if}
