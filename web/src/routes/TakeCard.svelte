<script lang="ts">
  import type { Durability, PricedIn, Recommendation, RecommendationPerformance, ScanRow } from '$lib/types';
  import { fmtPct, fmtPrice, pctClass } from '$lib/format';
  import { computeLevels, quickPlan, sizePosition, REFERENCE_EQUITY } from '$lib/levels';
  import { bandTrust, GRADE_CLASS } from '$lib/trust';
  import Sparkline from './Sparkline.svelte';

  // Compact desk-take card: the 11-block PickCard answered every question at
  // once; this answers the three that matter on a phone — what, at what
  // levels, and does this signal class actually pay. Everything else lives
  // one tap away on /t/[ticker]. The catalyst-quality strip (durability /
  // priced-in / entry-style) + sizing line surface the drift + size-and-survive
  // signals from the scanner overhaul; each hides when its field is absent.
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

  // --- Catalyst-quality + sizing (scanner overhaul) ----------------------------
  const durability = $derived(row.synthesis?.durability ?? null);
  const pricedIn = $derived(row.synthesis?.priced_in ?? null);
  // Prefer the scanner's sizing; fall back to the client-side mirror off the
  // displayed levels so the "how much" shows even before the host runs the new
  // scanner (same pattern as computeLevels for the levels themselves).
  const sizing = $derived(
    rec.risk ??
      (levels ? sizePosition(REFERENCE_EQUITY, levels.entry, rec.hard_stop ?? levels.stop) : null)
  );

  // Drift strength: structural (M&A/FDA) holds longest, soft (PR) least.
  const DURABILITY_META: Record<Durability, { label: string; cls: string }> = {
    structural: { label: 'structural', cls: 'text-signal-pred border-signal-pred/40' },
    guidance: { label: 'guidance', cls: 'text-signal-up border-signal-up/40' },
    surprise: { label: 'surprise', cls: 'text-signal-info border-signal-info/40' },
    soft: { label: 'soft', cls: 'text-zinc-500 border-zinc-600/50' }
  };
  // "no" = the actionable not-yet-priced-in call; "yes" = discounted, fade it.
  const PRICED_META: Record<PricedIn, { label: string; cls: string }> = {
    no: { label: 'not priced in', cls: 'text-signal-up border-signal-up/40' },
    contradicted: { label: 'tape disagrees', cls: 'text-signal-pred border-signal-pred/40' },
    partial: { label: 'partly priced', cls: 'text-signal-warn border-signal-warn/40' },
    yes: { label: 'priced in', cls: 'text-zinc-500 border-zinc-600/50' }
  };
</script>

<a href={`/t/${row.ticker}`} class="pick-card row-link lift {isLong ? 'pick-card-long' : 'pick-card-short'}">
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

  {#if durability || rec.entry_style || pricedIn || rec.horizon_days}
    <div class="mt-2 flex flex-wrap items-center gap-1">
      {#if durability && DURABILITY_META[durability]}
        <span
          class="rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wider {DURABILITY_META[
            durability
          ].cls}"
          title="Catalyst durability — how long the move tends to drift">
          {DURABILITY_META[durability].label}
        </span>
      {/if}
      {#if rec.entry_style}
        <span
          class="rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wider {rec.entry_style ===
          'base'
            ? 'text-signal-up border-signal-up/40'
            : 'text-signal-warn border-signal-warn/40'}"
          title="Buy the post-catalyst base, not the spike">
          {rec.entry_style === 'base' ? 'buy the base' : 'spike — wait'}
        </span>
      {/if}
      {#if pricedIn && PRICED_META[pricedIn]}
        <span
          class="rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wider {PRICED_META[
            pricedIn
          ].cls}"
          title="Whether the tape has already discounted the catalyst">
          {PRICED_META[pricedIn].label}
        </span>
      {/if}
      {#if rec.horizon_days}
        <span class="ml-auto text-[9px] uppercase tracking-wider text-zinc-500"
          >hold ~{rec.horizon_days}d</span
        >
      {/if}
    </div>
  {/if}

  {#if levels}
    <div class="mt-2 grid grid-cols-3 gap-2 rounded border border-ink-700/60 bg-ink-900/40 p-2 text-center">
      <div>
        <div class="text-[9px] uppercase tracking-wider text-zinc-500">entry</div>
        <div class="num text-sm text-zinc-100">${fmtPrice(levels.entry)}</div>
      </div>
      <div>
        <div class="text-[9px] uppercase tracking-wider text-zinc-500">stop</div>
        <div class="num text-sm text-signal-down">${fmtPrice(rec.hard_stop ?? levels.stop)}</div>
      </div>
      <div>
        <div class="text-[9px] uppercase tracking-wider text-zinc-500">target</div>
        <div class="num text-sm text-signal-up">${fmtPrice(levels.target)}</div>
      </div>
    </div>

    {#if sizing && sizing.shares > 0}
      <div class="mt-1 flex items-center justify-between text-[10px] text-zinc-400">
        <span>
          size <span class="num font-semibold text-zinc-200">{sizing.shares}</span> sh ·
          <span class="num">${Math.round(sizing.notional).toLocaleString()}</span>
        </span>
        <span class="text-zinc-500">
          {(sizing.pct_of_equity * 100).toFixed(1)}% of book{sizing.capped ? ' · capped' : ''}
        </span>
      </div>
    {/if}
  {/if}

  {#if plan}
    <p class="mt-2 line-clamp-3 text-xs leading-relaxed text-zinc-300">{plan}</p>
  {/if}
</a>
