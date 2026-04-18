<script lang="ts">
  import { fmtPct, fmtRelative } from '$lib/format';
  import type { AlertTypeStats } from '$lib/types';

  let { data } = $props();
  const perf = data.perf;

  const ALERT_TYPE_LABELS: Record<string, { label: string; emoji: string }> = {
    catalyst: { label: 'Catalyst', emoji: '🎯' },
    macro: { label: 'Macro', emoji: '🌍' },
    watchlist: { label: 'Watchlist', emoji: '⭐' },
    big_move: { label: 'Big move', emoji: '🚀' },
    delta_new_top20: { label: 'New top-20', emoji: '📈' },
    delta_rank_jump: { label: 'Rank jump', emoji: '⚡' },
    delta_accel: { label: 'Accel', emoji: '🌡️' },
    weekly: { label: 'Weekly', emoji: '📊' }
  };

  function hitClass(rate: number | null): string {
    if (rate == null) return 'text-zinc-500';
    if (rate >= 0.6) return 'text-signal-up';
    if (rate >= 0.45) return 'text-signal-warn';
    return 'text-signal-down';
  }

  function returnClass(n: number | null): string {
    if (n == null) return 'text-zinc-500';
    if (n > 0) return 'text-signal-up';
    if (n < 0) return 'text-signal-down';
    return 'text-zinc-400';
  }
</script>

<svelte:head>
  <title>Performance — Momentum</title>
</svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">Alert performance</h1>
  <p class="text-xs text-zinc-500">
    Is this tool actually finding alpha? Trailing 30-day hit rate + average return
    per alert type, measured 1/3/5 days after each alert. Return is signed in the
    direction of the alert.
  </p>
</header>

{#if !perf}
  <div class="card p-8 text-center text-zinc-400">
    <p class="text-sm">No performance data yet.</p>
    <p class="mt-2 text-xs">
      Stats accumulate as alerts are logged and their 1/3/5-day horizons pass.
      First meaningful data appears ~5 days after alerts start firing.
    </p>
  </div>
{:else if perf.total_alerts === 0}
  <div class="card p-8 text-center text-zinc-400">
    <p class="text-sm">No alerts fired in the last 30 days.</p>
  </div>
{:else}
  <section class="mb-6 flex flex-wrap items-center gap-2 text-xs">
    <span class="pill-info">{perf.total_alerts} alerts · last {perf.window_days}d</span>
    <span class="ml-auto text-zinc-500">updated {fmtRelative(perf.generated_at)}</span>
  </section>

  <section class="card overflow-x-auto">
    <table class="w-full text-xs">
      <thead class="bg-ink-800/40 text-[10px] uppercase tracking-wider text-zinc-500">
        <tr>
          <th class="px-3 py-2 text-left">Alert type</th>
          <th class="px-3 py-2 text-right">Fired</th>
          <th class="px-3 py-2 text-right">1d hit</th>
          <th class="px-3 py-2 text-right">1d avg</th>
          <th class="px-3 py-2 text-right">3d hit</th>
          <th class="px-3 py-2 text-right">3d avg</th>
          <th class="px-3 py-2 text-right">5d hit</th>
          <th class="px-3 py-2 text-right">5d avg</th>
        </tr>
      </thead>
      <tbody>
        {#each Object.entries(perf.per_type) as [type, stats]}
          {@const meta = ALERT_TYPE_LABELS[type] ?? { label: type, emoji: '•' }}
          <tr class="border-t border-ink-700/40">
            <td class="px-3 py-2">
              <span class="mr-1">{meta.emoji}</span>
              <span class="font-medium">{meta.label}</span>
            </td>
            <td class="num px-3 py-2 text-right text-zinc-400">{stats.count}</td>
            {#each ['1d', '3d', '5d'] as h}
              {@const hs = stats.horizons[h as '1d' | '3d' | '5d']}
              <td class="num px-3 py-2 text-right {hitClass(hs?.hit_rate ?? null)}">
                {hs?.hit_rate != null ? `${(hs.hit_rate * 100).toFixed(0)}%` : '—'}
                {#if hs?.evaluated != null}
                  <span class="text-[10px] text-zinc-600"> ({hs.evaluated})</span>
                {/if}
              </td>
              <td class="num px-3 py-2 text-right {returnClass(hs?.avg_return_pct ?? null)}">
                {hs?.avg_return_pct != null ? fmtPct(hs.avg_return_pct) : '—'}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </section>

  <p class="mt-4 text-[10px] uppercase tracking-wider text-zinc-500">
    Hit = alert's directional signal followed through (positive signed return after N days).
    Green cells are the alert types you should trust; red cells are signal-noise candidates.
    Evaluated count in parentheses shows how many alerts have actually hit that horizon yet.
  </p>
{/if}
