<script lang="ts">
  // Two treatments share the same component so the call sites stay simple:
  // - line  → SVG polyline (TickerCard, PickCard inset, anywhere with room)
  // - block → unicode ▁▂▃▄▅▆▇ (thin rows where SVG would dominate the cell)
  let {
    values,
    up = null,
    width = 100,
    height = 28,
    treatment = 'line',
    strokeWidth = 1.5
  }: {
    values: number[];
    up?: boolean | null;
    width?: number;
    height?: number;
    treatment?: 'line' | 'block';
    strokeWidth?: number;
  } = $props();

  const trendUp = $derived(
    up ?? (values && values.length >= 2 ? values[values.length - 1] > values[0] : null)
  );
  const strokeClass = $derived(
    trendUp == null ? 'text-zinc-500' : trendUp ? 'text-signal-up' : 'text-signal-down'
  );

  // SVG line treatment
  const path = $derived.by(() => {
    if (!values || values.length < 2) return '';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const n = values.length;
    const pts = values.map((v, i) => {
      const x = (i / (n - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return 'M' + pts.join(' L');
  });

  // Block treatment: bucket each value to one of 7 levels, render as a unicode
  // glyph. Limited resolution but renders in zero paint cost and reads as a
  // shape even when squeezed into a 60px cell.
  const BLOCKS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇'];
  const blockText = $derived.by(() => {
    if (!values || values.length < 2) return '';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    return values
      .map((v) => {
        const idx = Math.min(BLOCKS.length - 1, Math.floor(((v - min) / range) * BLOCKS.length));
        return BLOCKS[idx];
      })
      .join('');
  });
</script>

{#if values && values.length >= 2}
  {#if treatment === 'block'}
    <span class="spark-block {strokeClass}" aria-hidden="true">{blockText}</span>
  {:else}
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      class="h-7 w-full {strokeClass}"
    >
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        stroke-width={strokeWidth}
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  {/if}
{/if}
