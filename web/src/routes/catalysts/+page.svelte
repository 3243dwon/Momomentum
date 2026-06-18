<script lang="ts">
  import { fmtPct, pctClass, fmtRelative } from '$lib/format';
  import { reveal } from '$lib/reveal.svelte';
  import type { CatalystEvent, CatalystStance, ScanRow } from '$lib/types';

  let { data } = $props();

  const cat = $derived(data.catalysts);
  const scan = $derived(data.scan);

  // Live price/day-move per holding, joined from the scan.
  const priceByTicker = $derived.by(() => {
    const m = new Map<string, ScanRow>();
    for (const r of scan?.rows ?? []) m.set(r.ticker, r);
    return m;
  });

  const holdings = $derived(cat?.holdings ?? []);
  const macro = $derived(cat?.macro ?? []);
  const notes = $derived(cat?.notes_by_ticker ?? {});

  // Merged "soonest" strip: every holding catalyst + macro, sorted by date,
  // the nearest dozen. Macro events carry no ticker.
  const soonest = $derived.by((): CatalystEvent[] => {
    const all: CatalystEvent[] = [];
    for (const evs of Object.values(cat?.by_ticker ?? {})) all.push(...evs);
    all.push(...macro);
    return all
      .filter((e) => e.days_until >= 0)
      .sort((a, b) => a.days_until - b.days_until)
      .slice(0, 12);
  });

  function fmtDate(d: string): string {
    return new Date(d + 'T00:00:00').toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric'
    });
  }
  function dayBadge(du: number): string {
    if (du <= 0) return 'today';
    if (du === 1) return 'tomorrow';
    if (du < 21) return `${du} days`;
    if (du < 70) return `${du}d`;
    return `${Math.round(du / 7)}w`;
  }
  function dayPill(du: number): string {
    if (du <= 3) return 'pill-warn';
    if (du <= 14) return 'pill-info';
    return 'pill-flat';
  }

  const TYPE_META: Record<string, { icon: string; label: string }> = {
    earnings: { icon: '📊', label: 'Earnings' },
    ex_dividend: { icon: '💵', label: 'Ex-dividend' },
    macro: { icon: '🏛', label: 'Macro' },
    witching: { icon: '🌀', label: 'Witching' }
  };

  const STANCE: Record<CatalystStance, { cls: string; label: string }> = {
    'add-on-weakness': { cls: 'pill-up', label: 'add on weakness' },
    'trim-into-strength': { cls: 'pill-warn', label: 'trim into strength' },
    'reduce-risk': { cls: 'pill-down', label: 'reduce risk' },
    hold: { cls: 'pill-flat', label: 'hold' },
    watch: { cls: 'pill-info', label: 'watch' }
  };
  function stanceMeta(s: string) {
    return STANCE[s as CatalystStance] ?? { cls: 'pill-flat', label: s };
  }
</script>

<svelte:head>
  <title>Momentum — catalysts</title>
</svelte:head>

<header class="mb-6">
  <h1 class="font-display text-2xl font-black tracking-tight">Catalysts</h1>
  <p class="text-xs text-zinc-500">
    🗓 Your portfolio's dated add/trim windows — next earnings &amp; ex-dividend per holding, the US
    macro calendar, and quarterly witching, each with an Opus read. Edit
    <code class="text-zinc-400">data/portfolio.json</code> to change what's tracked.
  </p>
</header>

{#if !cat}
  <p class="card p-4 text-xs text-zinc-500">
    No catalyst data yet — the scanner writes it on its next run. Check back after the next scan.
  </p>
{:else if cat.status === 'no_portfolio'}
  <p class="card p-4 text-xs text-zinc-500">
    No holdings configured. Add tickers to <code class="text-zinc-400">data/portfolio.json</code> and
    the next scan will build your calendar.
  </p>
{:else}
  {#if cat.status === 'no_key'}
    <p class="card mb-4 p-3 text-xs text-signal-warn">
      FMP key not configured — earnings &amp; dividend dates are unavailable, so only the computed
      macro / witching calendar shows below. Set <code>FMP_API_KEY</code> to enable per-holding dates.
    </p>
  {/if}

  <!-- 1 · Soonest across everything -->
  {#if soonest.length > 0}
    <section class="mb-8" use:reveal>
      <header class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold tracking-tight">Soonest</h2>
        <span class="text-[10px] uppercase tracking-wider text-zinc-500">{cat.catalyst_count} tracked</span>
      </header>
      <div class="card divide-y divide-ink-700/40 overflow-hidden">
        {#each soonest as e (e.id)}
          <div class="flex items-center gap-3 p-3 text-xs">
            <span class="w-12 shrink-0 font-mono text-zinc-400">{fmtDate(e.date)}</span>
            <span class="pill {dayPill(e.days_until)} shrink-0">{dayBadge(e.days_until)}</span>
            <span class="shrink-0">{TYPE_META[e.type]?.icon ?? '•'}</span>
            {#if e.ticker}
              <a href={`/t/${e.ticker}`} class="w-14 shrink-0 font-mono font-semibold hover:text-signal-info">{e.ticker}</a>
            {:else}
              <span class="w-14 shrink-0 font-mono text-zinc-500">macro</span>
            {/if}
            <span class="min-w-0 flex-1 truncate text-zinc-300">{e.label}</span>
            {#if e.confidence === 'estimated'}
              <span class="pill pill-flat shrink-0">est.</span>
            {/if}
          </div>
        {/each}
      </div>
    </section>
  {/if}

  <!-- 2 · Per-holding -->
  <section class="mb-8" use:reveal>
    <h2 class="mb-3 text-sm font-semibold tracking-tight">By holding</h2>
    <div class="space-y-3">
      {#each holdings as h (h.ticker)}
        {@const events = cat.by_ticker[h.ticker] ?? []}
        {@const note = notes[h.ticker]}
        {@const row = priceByTicker.get(h.ticker)}
        <div class="card p-4">
          <header class="mb-2 flex flex-wrap items-center gap-2">
            <a href={`/t/${h.ticker}`} class="font-mono text-base font-bold hover:text-signal-info">{h.ticker}</a>
            {#if h.shares}<span class="text-[10px] uppercase tracking-wider text-zinc-500">{h.shares} sh</span>{/if}
            {#if row?.price != null}
              <span class="text-xs text-zinc-400">{row.price.toFixed(2)}</span>
              <span class="text-xs {pctClass(row.pct_1d)}">{fmtPct(row.pct_1d)}</span>
            {/if}
            <span class="flex-1"></span>
            {#if note}
              <span class="pill {stanceMeta(note.stance).cls}">{stanceMeta(note.stance).label}</span>
            {/if}
          </header>

          {#if note}
            <p class="mb-2 text-xs leading-relaxed text-zinc-300">{note.read}</p>
            <div class="mb-2 grid gap-1 text-[11px] sm:grid-cols-2">
              <p class="text-signal-up"><span class="text-zinc-500">bull ·</span> {note.bull}</p>
              <p class="text-signal-down"><span class="text-zinc-500">bear ·</span> {note.bear}</p>
            </div>
            <p class="mb-2 text-[10px] uppercase tracking-wider text-zinc-500">
              next · {note.next_catalyst}
            </p>
          {:else if h.note}
            <p class="mb-2 text-xs leading-relaxed text-zinc-500">{h.note}</p>
          {/if}

          {#if events.length > 0}
            <div class="divide-y divide-ink-700/40 border-t border-ink-700/40">
              {#each events as e (e.id)}
                <div class="flex items-center gap-3 py-2 text-xs">
                  <span class="w-12 shrink-0 font-mono text-zinc-400">{fmtDate(e.date)}</span>
                  <span class="pill {dayPill(e.days_until)} shrink-0">{dayBadge(e.days_until)}</span>
                  <span class="shrink-0">{TYPE_META[e.type]?.icon ?? '•'}</span>
                  <span class="min-w-0 flex-1">
                    <span class="text-zinc-300">{e.label}</span>
                    {#if e.detail}<span class="text-zinc-500"> · {e.detail}</span>{/if}
                  </span>
                  {#if e.confidence === 'estimated'}
                    <span class="pill pill-flat shrink-0">est.</span>
                  {:else}
                    <span class="pill pill-info shrink-0">confirmed</span>
                  {/if}
                </div>
              {/each}
            </div>
          {:else}
            <p class="border-t border-ink-700/40 pt-2 text-[11px] text-zinc-600">
              No scheduled earnings / dividend dates found{cat.status === 'no_key' ? '' : ' for the window'}.
            </p>
          {/if}
        </div>
      {/each}
    </div>
  </section>

  <!-- 3 · Macro calendar -->
  {#if macro.length > 0}
    <section class="mb-8" use:reveal>
      <h2 class="mb-3 text-sm font-semibold tracking-tight">Macro calendar</h2>
      <p class="mb-3 text-[11px] text-zinc-500">
        Portfolio-wide — these move the whole book via rates, hardest on the long-duration
        AI/semis names.
      </p>
      <div class="card divide-y divide-ink-700/40 overflow-hidden">
        {#each macro as e (e.id)}
          <div class="flex items-center gap-3 p-3 text-xs">
            <span class="w-12 shrink-0 font-mono text-zinc-400">{fmtDate(e.date)}</span>
            <span class="pill {dayPill(e.days_until)} shrink-0">{dayBadge(e.days_until)}</span>
            <span class="shrink-0">{TYPE_META[e.type]?.icon ?? '•'}</span>
            <span class="min-w-0 flex-1">
              <span class="text-zinc-300">{e.label}</span>
              {#if e.detail}<span class="text-zinc-500"> · {e.detail}</span>{/if}
            </span>
            {#if e.impact === 'high'}<span class="pill pill-warn shrink-0">high</span>{/if}
          </div>
        {/each}
      </div>
    </section>
  {/if}

  <!-- 4 · Methodology / honesty -->
  <footer class="space-y-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
    <p>
      Dates from FMP (earnings, dividends, macro) + computed triple-witching. Forward earnings are
      aggregator <span class="text-zinc-400">estimates</span>, not company-confirmed — confirm against
      the company's IR release (~2 weeks ahead). Dividends, macro prints and witching are scheduled.
    </p>
    {#if cat.disclaimer}<p>{cat.disclaimer}</p>{/if}
    <p>
      Calendar built {fmtRelative(cat.generated_at)}{#if cat.notes_generated_at}
        · reads {fmtRelative(cat.notes_generated_at)}{/if}. Not investment advice.
    </p>
  </footer>
{/if}
