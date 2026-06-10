<script lang="ts">
  import type { TradeLevels } from '$lib/types';

  // 20-day close line with the trade plan drawn on it: entry/stop/target from
  // the levels heuristic, plus intraday VWAP/HOD/LOD references when a live
  // session has produced them. Pure SVG — no chart library.
  let {
    values,
    levels = null,
    intraday = null,
    up = true
  }: {
    values: number[];
    levels?: TradeLevels | null;
    intraday?: { vwap: number | null; hod: number; lod: number } | null;
    up?: boolean;
  } = $props();

  const W = 340;
  const H = 150;
  const PAD_R = 52; // room for level labels
  const PAD_Y = 8;

  type Ref = { value: number; label: string; cls: string; dash: string };

  const refs = $derived.by(() => {
    const out: Ref[] = [];
    if (levels) {
      out.push(
        { value: levels.target, label: `T ${levels.target.toFixed(2)}`, cls: 'text-signal-up', dash: '4 3' },
        { value: levels.entry, label: `E ${levels.entry.toFixed(2)}`, cls: 'text-zinc-400', dash: '2 3' },
        { value: levels.stop, label: `S ${levels.stop.toFixed(2)}`, cls: 'text-signal-down', dash: '4 3' }
      );
    }
    if (intraday?.vwap != null) {
      out.push({ value: intraday.vwap, label: `vwap ${intraday.vwap.toFixed(2)}`, cls: 'text-signal-info', dash: '1 3' });
    }
    if (intraday) {
      out.push(
        { value: intraday.hod, label: `hod`, cls: 'text-zinc-600', dash: '1 4' },
        { value: intraday.lod, label: `lod`, cls: 'text-zinc-600', dash: '1 4' }
      );
    }
    return out;
  });

  const domain = $derived.by(() => {
    const all = [...values, ...refs.map((r) => r.value)].filter((v) => Number.isFinite(v));
    let min = Math.min(...all);
    let max = Math.max(...all);
    const pad = (max - min || max * 0.02 || 1) * 0.06;
    return { min: min - pad, max: max + pad };
  });

  function y(v: number): number {
    const { min, max } = domain;
    return PAD_Y + (1 - (v - min) / (max - min)) * (H - 2 * PAD_Y);
  }

  const xStep = $derived((W - PAD_R) / Math.max(values.length - 1, 1));
  const linePath = $derived(values.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * xStep).toFixed(1)},${y(v).toFixed(1)}`).join(' '));
  const areaPath = $derived(`${linePath} L${((values.length - 1) * xStep).toFixed(1)},${H} L0,${H} Z`);

  // Nudge labels apart when reference prices sit within a label-height of
  // each other.
  const labeled = $derived.by(() => {
    const sorted = refs
      .map((r) => ({ ...r, y: y(r.value), labelY: y(r.value) }))
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i].labelY - sorted[i - 1].labelY < 10) sorted[i].labelY = sorted[i - 1].labelY + 10;
    }
    return sorted;
  });

  const lineCls = $derived(up ? 'text-signal-up' : 'text-signal-down');
</script>

<svg viewBox="0 0 {W} {H}" class="w-full" role="img" aria-label="20-day price chart with trade levels">
  <defs>
    <linearGradient id="chart-fade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="currentColor" stop-opacity="0.18" />
      <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
    </linearGradient>
  </defs>

  {#each labeled as r (r.label + r.value)}
    <line x1="0" x2={W - PAD_R + 4} y1={r.y} y2={r.y} class={r.cls} stroke="currentColor" stroke-width="0.75" stroke-dasharray={r.dash} opacity="0.7" />
    <text x={W - PAD_R + 7} y={r.labelY + 2.5} class="num {r.cls}" fill="currentColor" font-size="8" opacity="0.9">{r.label}</text>
  {/each}

  <g class={lineCls}>
    <path d={areaPath} fill="url(#chart-fade)" />
    <path d={linePath} fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />
    {#if values.length}
      <circle cx={(values.length - 1) * xStep} cy={y(values[values.length - 1])} r="2.4" fill="currentColor" />
    {/if}
  </g>
</svg>
