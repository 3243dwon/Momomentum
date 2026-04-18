<script lang="ts">
  type Accent = 'up' | 'down' | 'warn' | 'info' | 'flat';
  let { label, value, accent = 'flat' }: { label: string; value: string; accent?: Accent } = $props();

  const accentClass: Record<Accent, string> = {
    up: 'border-signal-up/30 bg-signal-up/5 text-signal-up',
    down: 'border-signal-down/30 bg-signal-down/5 text-signal-down',
    warn: 'border-signal-warn/30 bg-signal-warn/5 text-signal-warn',
    info: 'border-signal-info/30 bg-signal-info/5 text-signal-info',
    flat: 'border-ink-700 bg-ink-900 text-zinc-400'
  };
</script>

<span class="inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] uppercase tracking-wider {accentClass[accent]}">
  <span class="text-zinc-500">{label}</span>
  <span class="font-medium text-zinc-100">{value}</span>
</span>
