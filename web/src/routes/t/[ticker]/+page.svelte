<script lang="ts">
  import { fmtPct, fmtPrice, fmtRelVol, fmtVolume, pctClass, fmtRelative, impactPill, confidencePill } from '$lib/format';

  let { data } = $props();
  const { ticker, row, news, macroMentions } = data;
</script>

<svelte:head>
  <title>{ticker} — Momentum</title>
</svelte:head>

<div class="mb-4 flex items-center gap-2 text-xs text-zinc-500">
  <a href="/" class="hover:text-zinc-300">← scan</a>
  <span>/</span>
  <span class="text-zinc-300">{ticker}</span>
</div>

{#if !row}
  <div class="card p-8 text-center">
    <p class="text-zinc-300">No scan data for <span class="font-semibold">{ticker}</span>.</p>
    <p class="mt-2 text-xs text-zinc-500">It may not be in the universe, or didn't pass the liquidity floor.</p>
  </div>
{:else}
  <section class="card mb-6 p-4">
    <div class="flex flex-wrap items-baseline justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">{ticker}</h1>
        <p class="text-xs text-zinc-500">last price ${fmtPrice(row.price)}</p>
      </div>
      <div class="flex items-baseline gap-4">
        <div class="text-right">
          <div class="text-[10px] uppercase tracking-wider text-zinc-500">1-day</div>
          <div class="num text-lg font-semibold {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</div>
        </div>
        <div class="text-right">
          <div class="text-[10px] uppercase tracking-wider text-zinc-500">5-day</div>
          <div class="num text-lg font-semibold {pctClass(row.pct_5d)}">{fmtPct(row.pct_5d)}</div>
        </div>
      </div>
    </div>

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

    {#if row.flags.length}
      <div class="mt-4 flex flex-wrap gap-1">
        {#each row.flags as flag}
          <span class="pill-flat">{flag.replace('_', ' ')}</span>
        {/each}
      </div>
    {/if}
  </section>

  {#if row.snapshot || row.intraday}
    <section class="card mb-6 p-4">
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">Intraday signals</h2>
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">pro-grade indicators</span>
      </header>
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
    </section>
  {/if}

  {#if row.synthesis}
    <section class="card mb-6 p-4">
      <header class="mb-2 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">Why it moved</h2>
        <div class="flex items-center gap-2 text-[10px] uppercase tracking-wider">
          <span class="pill {confidencePill(row.synthesis.confidence)}">conf · {row.synthesis.confidence}</span>
          <span class="pill-flat">{row.synthesis.verdict.replace(/_/g, ' ')}</span>
        </div>
      </header>
      <p class="text-sm leading-relaxed text-zinc-200">{row.synthesis.summary}</p>
    </section>
  {/if}

  {#if news.length > 0}
    <section class="card mb-6">
      <header class="border-b border-ink-700 px-4 py-2">
        <h2 class="text-sm font-semibold tracking-tight">News ({news.length})</h2>
      </header>
      <ul class="divide-y divide-ink-700/60">
        {#each news as item (item.id)}
          <li class="px-4 py-3">
            <div class="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500">
              <span>{item.publisher || item.source}</span>
              <span>·</span>
              <span>{fmtRelative(item.published_at)}</span>
              {#if item.type}<span class="pill-flat">{item.type.replace('_', ' ')}</span>{/if}
              {#if item.impact}<span class="pill {impactPill(item.impact)}">{item.impact}</span>{/if}
            </div>
            <a href={item.url} target="_blank" rel="noopener noreferrer" class="text-sm leading-snug text-zinc-200 hover:text-signal-info">
              {item.title}
            </a>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if macroMentions.length > 0}
    <section class="card mb-6">
      <header class="border-b border-ink-700 px-4 py-2">
        <h2 class="text-sm font-semibold tracking-tight">Macro context</h2>
      </header>
      <ul class="divide-y divide-ink-700/60">
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
{/if}
