<script lang="ts">
  import { FLAG_META, TONE_CLASS, type TickerFlag } from '$lib/flags';

  // Renders up to `max` flag chips; the rest collapse into a "+N" chip whose
  // tooltip lists the truncated labels so they aren't lost — just demoted.
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

  // Tone background classes — use signal/10 wash so chips stay subtle next to
  // the row's primary number (% change). Mute uses ink-700 for neutral grey.
  const TONE_BG: Record<string, string> = {
    'text-signal-up':   'bg-signal-up/10',
    'text-signal-down': 'bg-signal-down/10',
    'text-signal-warn': 'bg-signal-warn/10',
    'text-signal-info': 'bg-signal-info/10',
    'text-zinc-500':    'bg-ink-700/60',
    // TRUMP chip — stronger fill + ring so it pops above the other flags.
    'text-purple-300':  'bg-purple-500/20 ring-1 ring-purple-400/30'
  };

  const sizeClass = $derived(
    size === 'md' ? 'text-[11px] px-1.5 py-0.5' :
    size === 'xs' ? 'text-[9px] px-1 py-px' :
    'text-[10px] px-1.5 py-0.5'
  );
</script>

{#if flags.length > 0}
  <span class="inline-flex items-center gap-1">
    {#each visible as flag (flag)}
      {@const meta = FLAG_META[flag]}
      {@const tone = TONE_CLASS[meta.tone]}
      <span
        class="rounded font-mono uppercase tracking-wider leading-none whitespace-nowrap {sizeClass} {tone} {TONE_BG[tone]}"
        title={meta.tip}
        aria-label={meta.tip}
      >{meta.label}</span>
    {/each}
    {#if overflow.length > 0}
      <span
        class="rounded font-mono leading-none tabular-nums whitespace-nowrap {sizeClass} text-zinc-500 bg-ink-700/60"
        title={overflow.map((f) => `${FLAG_META[f].label} — ${FLAG_META[f].tip}`).join('\n')}
      >+{overflow.length}</span>
    {/if}
  </span>
{/if}
