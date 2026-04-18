<script lang="ts">
  let { values, up = null, width = 100, height = 28 }: {
    values: number[];
    up?: boolean | null;
    width?: number;
    height?: number;
  } = $props();

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

  const trendUp = $derived(
    up ?? (values && values.length >= 2 ? values[values.length - 1] > values[0] : null)
  );
  const strokeClass = $derived(trendUp == null ? 'text-zinc-500' : trendUp ? 'text-signal-up' : 'text-signal-down');
</script>

{#if values && values.length >= 2}
  <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" class="h-7 w-full {strokeClass}">
    <path d={path} fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
{/if}
