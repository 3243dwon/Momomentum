<script lang="ts">
  import type { NewsItem, Recommendation, ScanRow } from '$lib/types';
  import { fmtPct, fmtPrice, pctClass, fmtRelative } from '$lib/format';
  import { flagsFor } from '$lib/flags';
  import { computeLevels } from '$lib/levels';
  import Sparkline from './Sparkline.svelte';
  import IconCluster from './IconCluster.svelte';

  let {
    rec,
    row,
    rank,
    news = [],
    trumpMention = false
  }: {
    rec: Recommendation;
    row: ScanRow;
    rank: number;
    news?: NewsItem[];
    trumpMention?: boolean;
  } = $props();

  const isLong = rec.direction === 'long';
  const synth = row.synthesis;
  const newsHigh = news.some((n) => n.impact === 'high');

  const flags = $derived(flagsFor({ row, newsHigh, trumpMention }));

  // Heuristic trade levels derived from recent price action (see lib/levels.ts).
  const levels = $derived(computeLevels(row, rec.direction));

  // Tier-4 agent-desk verdict (Signal/Research/Risk/PM). Dim the card when the
  // desk passes or Risk vetoes — recommend.py still surfaced it, but the desk
  // disagrees, and that disagreement should be loud.
  const desk = $derived(rec.desk ?? null);
  const deskDemoted = $derived(!!desk && (desk.decision === 'pass' || desk.risk?.veto === true));
  const voteGlyph = (v?: string) => (v === 'agree' ? '✓' : v === 'against' ? '✕' : '~');
  const voteClass = (v?: string) =>
    v === 'agree' ? 'text-signal-up' : v === 'against' ? 'text-signal-down' : 'text-zinc-500';

  // Top headline shown as a one-liner under the synthesis. Dedup by id then
  // pick highest impact / most recent.
  const headlines = [...new Map(news.map((n) => [n.id, n])).values()]
    .sort((a, b) => {
      const impactRank = (n: NewsItem) => (n.impact === 'high' ? 0 : 1);
      return impactRank(a) - impactRank(b) || b.published_at.localeCompare(a.published_at);
    })
    .slice(0, 2);
</script>

<a
  href={`/t/${row.ticker}`}
  class="pick-card row-link {isLong ? 'pick-card-long' : 'pick-card-short'} {deskDemoted ? 'opacity-60' : ''}"
>
  <!-- Row 1: rank / ticker / direction badge -->
  <div class="flex items-baseline justify-between gap-2">
    <div class="flex items-baseline gap-2">
      <span class="num text-[10px] uppercase tracking-wider text-zinc-500">#{rank} pick</span>
    </div>
    <span
      class="rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider {isLong
        ? 'border-signal-up/40 text-signal-up'
        : 'border-signal-down/40 text-signal-down'}"
    >
      {isLong ? '▲ long' : '▼ short'}
    </span>
  </div>

  <!-- Row 2: large ticker -->
  <div class="mt-1 flex items-baseline justify-between gap-3">
    <h3 class="text-3xl font-bold tracking-tight text-zinc-100">{row.ticker}</h3>
    <span class="num text-xs text-zinc-500">${fmtPrice(row.price)}</span>
  </div>

  <!-- Row 3: hero % change (Playfair display) + readable inset sparkline -->
  <div class="mt-2 flex items-end justify-between gap-3">
    <span class="font-display text-4xl font-black leading-none tabular-nums {pctClass(row.pct_1d)}">
      {fmtPct(row.pct_1d)}
    </span>
    {#if row.spark && row.spark.length >= 2}
      <div class="h-9 w-28 shrink-0 opacity-90">
        <Sparkline values={row.spark} up={isLong} height={36} strokeWidth={1.75} />
      </div>
    {/if}
  </div>

  <!-- Row 4: conviction + icon cluster -->
  <div class="mt-3 flex items-center justify-between border-t border-ink-700/60 pt-2.5">
    <div class="flex items-baseline gap-1.5">
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">conviction</span>
      <span class="font-display text-xl font-bold leading-none text-zinc-100 tabular-nums">{rec.score}</span>
    </div>
    <IconCluster {flags} max={3} size="sm" />
  </div>

  <!-- Agent desk verdict — each agent's actual take, not just a glyph -->
  {#if desk}
    <div
      class="mt-2.5 rounded border p-2 {deskDemoted
        ? 'border-signal-down/30 bg-signal-down/5'
        : 'border-ink-700/60 bg-ink-800/30'}"
    >
      <div class="mb-1.5 flex items-center justify-between">
        <span
          class="text-[10px] font-semibold uppercase tracking-wider {desk.decision === 'take'
            ? 'text-signal-up'
            : 'text-signal-down'}"
        >
          desk: {desk.decision ?? '—'}{desk.size && desk.size !== 'none' ? ` · ${desk.size}` : ''}
        </span>
        {#if desk.agreement}
          <span class="text-[9px] uppercase tracking-wider text-zinc-500">{desk.agreement}</span>
        {/if}
      </div>
      <ul class="space-y-0.5 text-[11px] leading-snug">
        {#if desk.signal}
          <li class="flex gap-1.5">
            <span class="w-14 shrink-0 uppercase tracking-wider text-zinc-500">signal</span>
            <span class="shrink-0 {voteClass(desk.signal.vote)}">{voteGlyph(desk.signal.vote)}</span>
            <span class="text-zinc-300">{desk.signal.note}</span>
          </li>
        {/if}
        {#if desk.research}
          <li class="flex gap-1.5">
            <span class="w-14 shrink-0 uppercase tracking-wider text-zinc-500">research</span>
            <span class="shrink-0 {voteClass(desk.research.vote)}">{voteGlyph(desk.research.vote)}</span>
            <span class="text-zinc-300">{desk.research.note}</span>
          </li>
        {/if}
        {#if desk.risk}
          <li class="flex gap-1.5">
            <span class="w-14 shrink-0 uppercase tracking-wider text-zinc-500">risk</span>
            <span class="shrink-0 {desk.risk.veto ? 'font-semibold text-signal-down' : 'text-zinc-500'}">{desk.risk.veto ? '⚑' : '✓'}</span>
            <span class={desk.risk.veto ? 'text-signal-down' : 'text-zinc-300'}>{desk.risk.concern}</span>
          </li>
        {/if}
      </ul>
      {#if desk.rationale}
        <p class="mt-1.5 border-t border-ink-700/40 pt-1 text-[11px] leading-snug text-zinc-400">
          <span class="text-zinc-500">PM:</span> {desk.rationale}
        </p>
      {/if}
    </div>
  {/if}

  <!-- Trade levels (heuristic, derived from recent price action) -->
  {#if levels}
    <div class="mt-2.5 rounded border border-ink-700/60 bg-ink-800/30 p-2">
      <div class="mb-1 flex items-center justify-between">
        <span class="text-[9px] uppercase tracking-wider text-zinc-500">
          levels · {levels.pivotLabel} ${fmtPrice(levels.pivot)}
        </span>
        {#if levels.rr != null}
          <span
            class="num text-[10px] font-semibold {levels.rr >= 2 ? 'text-signal-up' : 'text-zinc-400'}"
            title="reward : risk"
          >{levels.rr.toFixed(1)}R</span>
        {/if}
      </div>
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
    </div>
  {/if}

  <!-- Why -->
  {#if synth?.summary}
    <p class="mt-2.5 line-clamp-2 text-xs leading-relaxed text-zinc-300">
      <span class="text-zinc-500">why:</span>
      {synth.summary}
    </p>
  {/if}

  <!-- Top headlines -->
  {#if headlines.length > 0}
    <ul class="mt-2 space-y-1">
      {#each headlines as item (item.id)}
        <li class="flex items-baseline justify-between gap-2">
          <span class="line-clamp-1 text-[11px] text-zinc-400">
            {#if item.impact === 'high'}<span class="text-signal-warn" title="high impact">●</span> {/if}{item.title}
          </span>
          <span class="num shrink-0 text-[10px] text-zinc-500">{fmtRelative(item.published_at)}</span>
        </li>
      {/each}
    </ul>
  {/if}

  <!-- Reasons (kept as text tags, not pills, so IconCluster owns the visual badge channel) -->
  {#if rec.reasons.length > 0}
    <p class="num mt-2 text-[10px] leading-relaxed text-zinc-500">
      {rec.reasons.slice(0, 4).join(' · ')}
    </p>
  {/if}
</a>
