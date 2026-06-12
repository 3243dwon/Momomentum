<script lang="ts">
  // Cold open — the scanner's funnel played as the front door. 5,370 symbols
  // materialize, collapse to today's scan, the real heat sparks across the
  // field, the movers surface with their sparklines, and the briefing speaks
  // in the house serif — then the page unpins onto the live dashboard.
  // Every glyph and number is real (scan.json / briefing.json). Plays once
  // per session, always skippable; reduced-motion users never see it.
  import { Scrub, phase } from '$lib/scrub.svelte';
  import type { ScanData } from '$lib/types';

  let {
    scan,
    headline,
    dismiss
  }: { scan: ScanData; headline: string | null; dismiss: () => void } = $props();

  const sc = new Scrub();
  const attach = sc.attach;
  const p = $derived(sc.progress);

  const mobile = typeof window !== 'undefined' && window.innerWidth < 640;
  const CAP = mobile ? 120 : 420;

  // The field: real tickers scattered across the viewport in three parallax
  // depths. Positions are a deterministic hash of the symbol — stable across
  // renders, no randomness. Hot = the scan flagged it.
  function hash(t: string): number {
    let h = 2166136261;
    for (let i = 0; i < t.length; i++) h = ((h ^ t.charCodeAt(i)) * 16777619) >>> 0;
    return h;
  }
  const glyphs = $derived(
    scan.rows.slice(0, CAP).map((r, i) => {
      const h = hash(r.ticker);
      return {
        t: r.ticker,
        hot: (r.flags?.length ?? 0) > 0,
        up: (r.pct_1d ?? 0) >= 0,
        layer: i % 3,
        x: 2 + (h % 911) / 911 * 96,
        y: 4 + ((h >>> 10) % 797) / 797 * 90
      };
    })
  );

  const movers = $derived(
    [...scan.rows]
      .sort((a, b) => Math.abs(b.pct_1d ?? 0) - Math.abs(a.pct_1d ?? 0))
      .slice(0, mobile ? 8 : 12)
  );

  const BLOCKS = '▁▂▃▄▅▆▇';
  function sparkOf(closes: number[] | undefined): string {
    if (!closes?.length) return '';
    const tail = closes.slice(-14);
    const lo = Math.min(...tail);
    const span = Math.max(...tail) - lo || 1;
    return tail.map((v) => BLOCKS[Math.min(6, Math.round(((v - lo) / span) * 6))]).join('');
  }

  // ── choreography: every visual is a pure function of scroll progress ──
  const counter = $derived(
    Math.round(scan.universe_size + (scan.row_count - scan.universe_size) * phase(p, 0.06, 0.3))
  );
  const counterLabel = $derived(
    p < 0.32 ? 'symbols in the universe' : p < 0.55 ? `made the scan — today's heat` : 'made the scan'
  );

  const dim = $derived(0.5 - 0.43 * phase(p, 0.08, 0.3)); // unflagged glyphs fade to texture
  const heat = $derived(phase(p, 0.3, 0.52)); // flagged glyphs take their real colors
  const blur = $derived(2.5 * phase(p, 0.55, 0.72)); // depth beat: field recedes
  const fieldOut = $derived(1 - 0.85 * phase(p, 0.78, 0.9));
  const counterOp = $derived(1 - phase(p, 0.55, 0.62));
  const moversOp = $derived(1 - phase(p, 0.78, 0.84));
  const statsOp = $derived(phase(p, 0.88, 0.93));
  const cueOp = $derived(phase(p, 0.93, 0.97));

  const words = $derived((headline ?? '').split(/\s+/).filter(Boolean));
  const wordAt = (i: number) => 0.78 + (i / Math.max(words.length, 1)) * 0.1;

  // Regime fails soft to {} upstream, so every numeric field needs coercion.
  const regime = $derived(scan.regime ?? null);
  const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);
  const spy = $derived(num(regime?.spy_pct_1d));
  const qqq = $derived(num(regime?.qqq_pct_1d));
  const vxx = $derived(num(regime?.vxx_stress_ratio));
  const REGIME_TONE: Record<string, string> = {
    risk_on: 'pill-up',
    risk_off: 'pill-down',
    mixed: 'pill-warn'
  };

  function fmtSigned(n: number | null | undefined): string {
    if (n == null) return '–';
    return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
  }

  // Seen = the story finished (or was skipped). Next session loads straight
  // onto the dashboard — this is a daily-use tool, not a theme park.
  $effect(() => {
    if (p > 0.96) {
      try {
        sessionStorage.setItem('momentum:seen-intro', '1');
      } catch {
        /* private mode */
      }
    }
  });

  function skip() {
    try {
      sessionStorage.setItem('momentum:seen-intro', '1');
    } catch {
      /* private mode */
    }
    dismiss();
    window.scrollTo(0, 0);
  }
</script>

<div class="relative -mx-4 h-[300vh] sm:-mx-6 lg:-mx-8" use:attach>
  <div
    class="cold-stage sticky top-0 flex h-[100svh] flex-col items-center justify-center overflow-hidden"
    style="--dim:{dim}; --heat:{heat};"
  >
    <!-- the universe: real ticker glyphs in three parallax depths -->
    <div
      class="pointer-events-none absolute inset-0"
      style="opacity:{fieldOut}; filter: blur({blur}px);"
    >
      {#each [0, 1, 2] as layer}
        <div class="absolute inset-0" style="transform: translateY({(-18 - layer * 16) * p}px);">
          {#each glyphs as g (g.t)}
            {#if g.layer === layer}
              <span
                class="cold-glyph absolute -translate-x-1/2 font-mono text-[10px] uppercase sm:text-[11px] {g.hot
                  ? g.up
                    ? 'cold-hot-up'
                    : 'cold-hot-down'
                  : ''}"
                style="left:{g.x}%; top:{g.y}%;">{g.t}</span
              >
            {/if}
          {/each}
        </div>
      {/each}
    </div>

    <!-- the count: universe -> scan -->
    <div class="pointer-events-none relative text-center" style="opacity:{counterOp};">
      <div class="num text-6xl font-semibold tracking-tight sm:text-8xl">
        {counter.toLocaleString()}
      </div>
      <div class="mt-3 text-[10px] uppercase tracking-wider text-zinc-500">{counterLabel}</div>
    </div>

    <!-- the movers: today's top of the tape, real sparks -->
    <div
      class="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 px-6"
      style="opacity:{moversOp};"
    >
      <div class="mx-auto w-full max-w-md space-y-1.5">
        {#each movers as m, i (m.ticker)}
          {@const t = phase(p, 0.55 + i * 0.013, 0.62 + i * 0.013)}
          <div
            class="flex items-baseline gap-3 font-mono text-xs sm:text-sm"
            style="opacity:{t}; transform: translateY({8 * (1 - t)}px);"
          >
            <span class="w-12 font-semibold sm:w-14">{m.ticker}</span>
            <span class="spark-block flex-1 text-zinc-500">{sparkOf(m.spark)}</span>
            <span class="num {(m.pct_1d ?? 0) >= 0 ? 'text-signal-up' : 'text-signal-down'}"
              >{fmtSigned(m.pct_1d)}</span
            >
          </div>
        {/each}
      </div>
    </div>

    <!-- the briefing speaks -->
    {#if words.length}
      <div class="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 px-6 text-center">
        <h2
          class="mx-auto max-w-3xl font-display text-3xl font-black leading-tight sm:text-5xl"
        >
          {#each words as w, i}
            <span style="opacity:{phase(p, wordAt(i), wordAt(i) + 0.03)};">{w}{' '}</span>
          {/each}
        </h2>
        {#if regime?.label}
          <div
            class="mt-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs"
            style="opacity:{statsOp};"
          >
            <span class="pill {REGIME_TONE[regime.label] ?? 'pill-flat'}"
              >{regime.label.replace('_', ' ')}</span
            >
            {#if spy != null}
              <span class="num {spy >= 0 ? 'text-signal-up' : 'text-signal-down'}"
                >SPY {fmtSigned(spy)}</span
              >
            {/if}
            {#if qqq != null}
              <span class="num {qqq >= 0 ? 'text-signal-up' : 'text-signal-down'}"
                >QQQ {fmtSigned(qqq)}</span
              >
            {/if}
            {#if vxx != null}
              <span class="num text-zinc-400">VXX ×{vxx.toFixed(2)}</span>
            {/if}
          </div>
        {/if}
        <div
          class="mt-8 flex items-center justify-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500"
          style="opacity:{cueOp};"
        >
          <span class="relative flex h-1.5 w-1.5">
            <span
              class="absolute inline-flex h-full w-full animate-ping rounded-full bg-signal-up opacity-60"
            ></span>
            <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-signal-up"></span>
          </span>
          scroll to enter the tape
        </div>
      </div>
    {/if}

    <!-- affordances -->
    <button
      type="button"
      onclick={skip}
      class="absolute right-4 top-4 z-10 rounded px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-500 transition-colors hover:bg-ink-800 hover:text-zinc-300"
      >skip intro ↓</button
    >
    <div
      class="pointer-events-none absolute inset-x-0 bottom-6 text-center text-[10px] uppercase tracking-wider text-zinc-600"
      style="opacity:{1 - phase(p, 0.02, 0.08)};"
    >
      scroll ↓
    </div>
  </div>
</div>

<style>
  .cold-stage {
    animation: cold-fade 0.7s ease-out both;
  }
  @keyframes cold-fade {
    from {
      opacity: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .cold-stage {
      animation: none;
    }
  }
  .cold-glyph {
    color: rgb(var(--text-500) / var(--dim));
  }
  .cold-hot-up {
    color: rgb(var(--signal-up) / calc(var(--dim) + (0.95 - var(--dim)) * var(--heat)));
  }
  .cold-hot-down {
    color: rgb(var(--signal-down) / calc(var(--dim) + (0.95 - var(--dim)) * var(--heat)));
  }
</style>
