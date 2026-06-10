<script lang="ts">
  import type { Recommendation, RecommendationPerformance, ScanRow } from '$lib/types';
  import { fmtPct, fmtPrice, pctClass } from '$lib/format';
  import { computeLevels, quickPlan } from '$lib/levels';
  import { bandTrust, GRADE_CLASS } from '$lib/trust';
  import Sparkline from './Sparkline.svelte';

  // Compact desk-take card: the 11-block PickCard answered every question at
  // once; this answers the three that matter on a phone — what, at what
  // levels, and does this signal class actually pay. Everything else lives
  // one tap away on /t/[ticker].
  let {
    rec,
    row,
    recPerf = null
  }: {
    rec: Recommendation;
    row: ScanRow;
    recPerf?: RecommendationPerformance | null;
  } = $props();

  const isLong = rec.direction === 'long';
  const levels = $derived(rec.levels ?? computeLevels(row, rec.direction));
  const plan = $derived(
    rec.desk?.plan && rec.desk.decision === 'take' ? rec.desk.plan : levels ? quickPlan(levels) : null
  );
  // Track record for this pick's score band — the conviction number with a
  // receipt attached.
  const trust = $derived(bandTrust(recPerf, rec.direction, rec.score));
</script>

<a href={`/t/${row.ticker}`} class="pick-card row-link {isLong ? 'pick-card-long' : 'pick-card-short'}">
  <div class="flex items-baseline justify-between gap-2">
    <div class="flex items-baseline gap-2">
      <h3 class="text-2xl font-bold tracking-tight text-zinc-100">{row.ticker}</h3>
      <span class="num text-xs text-zinc-500">${fmtPrice(row.price)}</span>
      <span class="num text-sm font-semibold {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</span>
    </div>
    <span
      class="rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider {isLong
        ? 'border-signal-up/40 text-signal-up'
        : 'border-signal-down/40 text-signal-down'}"
    >
      {isLong ? '▲ long' : '▼ short'}
    </span>
  </div>

  <div class="mt-1.5 flex items-center justify-between gap-3">
    {#if row.spark && row.spark.length >= 2}
      <Sparkline values={row.spark} up={(row.pct_1d ?? 0) >= 0} treatment="block" />
    {:else}
      <span></span>
    {/if}
    <div class="flex items-baseline gap-1.5 whitespace-nowrap">
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">conviction</span>
      <span class="num text-base font-semibold text-zinc-100">{rec.score}</span>
      {#if rec.desk?.size && rec.desk.size !== 'none'}
        <span class="pill-info">{rec.desk.size}</span>
      {/if}
    </div>
  </div>

  {#if trust}
    <p class="mt-1 text-[10px] {GRADE_CLASS[trust.grade]}">
      this score band, 5d: {trust.label}
    </p>
  {/if}

  {#if levels}
    <div class="mt-2 grid grid-cols-3 gap-2 rounded border border-ink-700/60 bg-ink-900/40 p-2 text-center">
      <div>
        <div class="text-[9px] uppercase tracking-wider text-zinc-500">entry</div>
        <div class="num text-sm text-zinc-100">${fmtPrice(levels.entry)}</div>
      </div>
      <div>
        <div class="text-[9px] uppercase tracking-wider text-zinc-500">stop</div>
        <div class="num text-sm text-signal-down">${fmtPrice(levels.stop)}</div>
      </div>
      <div>
        <div class="text-[9px] uppercase tracking-wider text-zinc-500">target</div>
        <div class="num text-sm text-signal-up">${fmtPrice(levels.target)}</div>
      </div>
    </div>
  {/if}

  {#if plan}
    <p class="mt-2 line-clamp-3 text-xs leading-relaxed text-zinc-300">{plan}</p>
  {/if}
</a>
