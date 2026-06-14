<script lang="ts">
  // Big-format mover: the day's leaders get a real chart card instead of a
  // skinny row — large mono percentage, 20-day area spark, directional wash.
  import type { ScanRow } from '$lib/types';
  import { fmtPrice } from '$lib/format';
  import { tilt } from '$lib/tilt.svelte';

  let { row, rank }: { row: ScanRow; rank: number } = $props();

  const up = $derived((row.pct_1d ?? 0) >= 0);

  const W = 100;
  const H = 34;
  const line = $derived.by(() => {
    const s = row.spark ?? [];
    if (s.length < 2) return '';
    const lo = Math.min(...s);
    const span = Math.max(...s) - lo || 1;
    return s
      .map((v, i) => `${((i / (s.length - 1)) * W).toFixed(1)},${(H - 2 - ((v - lo) / span) * (H - 6)).toFixed(1)}`)
      .join(' ');
  });
</script>

<a
  href={`/t/${row.ticker}`}
  use:tilt
  class="pick-card tilt block {up ? 'pick-card-long' : 'pick-card-short'}"
>
  <div class="flex items-baseline justify-between gap-2">
    <span class="flex items-baseline gap-2">
      <span class="text-[10px] uppercase tracking-wider text-zinc-500">#{rank}</span>
      <span class="font-mono text-lg font-bold tracking-tight">{row.ticker}</span>
    </span>
    <span class="num text-xs text-zinc-400">${fmtPrice(row.price)}</span>
  </div>

  <div class="num mt-1 text-3xl font-bold tracking-tight {up ? 'text-signal-up' : 'text-signal-down'}">
    {(row.pct_1d ?? 0) > 0 ? '+' : ''}{row.pct_1d?.toFixed(2)}%
  </div>

  {#if line}
    <svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" class="mt-2 h-12 w-full {up ? 'text-signal-up' : 'text-signal-down'}" aria-hidden="true">
      <polygon points="0,{H} {line} {W},{H}" fill="currentColor" opacity="0.12" />
      <polyline points={line} fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" />
    </svg>
  {/if}

  <div class="mt-2 flex flex-wrap items-center gap-1">
    {#if row.rel_volume != null && row.rel_volume >= 2}
      <span class="pill pill-warn">vol ×{row.rel_volume.toFixed(1)}</span>
    {/if}
    {#each (row.flags ?? []).slice(0, 2) as f (f)}
      <span class="pill pill-flat">{f.replace(/_/g, ' ')}</span>
    {/each}
  </div>
</a>
