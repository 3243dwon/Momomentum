<script lang="ts">
  import { FLAG_META, TONE_CLASS, type TickerFlag } from '$lib/flags';

  // ≤ max icons rendered, rest collapsed to " +N". Tooltip on the overflow
  // chip lists the truncated flags so they're not invisible — just demoted.
  let {
    flags,
    max = 3,
    size = 'sm'
  }: {
    flags: TickerFlag[];
    max?: number;
    size?: 'xs' | 'sm' | 'md';
  } = $props();

  const visible = $derived(flags.slice(0, max));
  const overflow = $derived(flags.slice(max));

  const sizeClass = $derived(
    size === 'md' ? 'text-base' : size === 'xs' ? 'text-[10px]' : 'text-xs'
  );
</script>

{#if flags.length > 0}
  <span class="inline-flex items-center gap-1.5 leading-none {sizeClass}">
    {#each visible as flag (flag)}
      {@const meta = FLAG_META[flag]}
      <span class={TONE_CLASS[meta.tone]} title={meta.label} aria-label={meta.label}>{meta.glyph}</span>
    {/each}
    {#if overflow.length > 0}
      <span
        class="text-zinc-500 tabular-nums"
        title={overflow.map((f) => FLAG_META[f].label).join(' · ')}
      >+{overflow.length}</span>
    {/if}
  </span>
{/if}
