<script lang="ts">
  // The Trust Trial — a pinned, scroll-scrubbed prologue to the signal
  // scoreboard. Five signals walk toward the 55% line and get stamped by the
  // same thresholds as the table below; nothing in the stage is scripted.
  import { Scrub, phase, prefersReducedMotion } from '$lib/scrub.svelte';
  import { signalTrust, type TrustGrade } from '$lib/trust';
  import type { PerformanceData } from '$lib/types';

  let { perf }: { perf: PerformanceData | null } = $props();

  // Same order + names as the scoreboard table — the trial must never
  // disagree with the table it introduces. No emoji: the stage is typographic.
  const ORDER = ['catalyst', 'big_move', 'delta_new_top20', 'serenity_match', 'ripple'];
  const LABELS: Record<string, string> = {
    catalyst: 'Catalyst',
    big_move: 'Big move',
    delta_new_top20: 'New top-20',
    serenity_match: 'Serenity match',
    ripple: 'Ripple'
  };

  // Bar scale: 0..70% hit rate maps to full track width, so the 45/55
  // threshold lines land mid-stage instead of hugging the right edge.
  const SCALE_MAX = 70;
  const pct = (v: number) => Math.min(100, (v / SCALE_MAX) * 100);
  const NOISE_X = pct(45);
  const TRUST_X = pct(55);

  interface TrialRow {
    type: string;
    label: string;
    gross: number; // 1d hit rate, 0-100
    net: number | null; // after slippage drag — absent in live data today
    n: number; // evaluated at 1d
    grade: TrustGrade;
  }

  const rows = $derived.by(() => {
    if (!perf?.per_type) return [] as TrialRow[];
    const out: TrialRow[] = [];
    for (const type of ORDER) {
      const h = perf.per_type[type]?.horizons?.['1d'];
      if (h?.hit_rate == null) continue;
      out.push({
        type,
        label: LABELS[type] ?? type.replace(/_/g, ' '),
        gross: h.hit_rate * 100,
        net: h.hit_rate_net != null ? h.hit_rate_net * 100 : null,
        n: h.evaluated ?? 0,
        grade: signalTrust(perf, type, '1d')?.grade ?? 'unproven'
      });
    }
    return out;
  });

  const hasNet = $derived(rows.some((r) => r.net != null));
  const reduced = prefersReducedMotion();

  const sc = new Scrub();
  const attach = sc.attach;

  interface TrialFrame {
    chip: number; // slippage chip opacity (hasNet only)
    rows: { value: number; fill: number; ghostW: number; stamped: boolean }[];
  }

  // One pure frame(p): the pinned stage renders frame(progress), the
  // reduced-motion fallback renders frame(1) — same code path, no second truth.
  function frame(p: number): TrialFrame {
    const grow = phase(p, 0, hasNet ? 0.4 : 0.55);
    const shave = hasNet ? phase(p, 0.4, 0.62) : 0;
    const stampStart = hasNet ? 0.7 : 0.65;
    return {
      chip: shave,
      rows: rows.map((r, i) => {
        const grown = r.gross * grow;
        // Shave only moves once grow is done (phases share the 0.40 boundary).
        const value = grown - (r.net != null ? (r.gross - r.net) * shave : 0);
        return {
          value,
          fill: pct(value),
          ghostW: r.net != null ? pct(grown) - pct(value) : 0,
          stamped: p >= stampStart + (0.95 - stampStart) * (i / Math.max(rows.length, 1))
        };
      })
    };
  }

  const TINT: Record<TrustGrade, string> = {
    trusted: 'bg-signal-up',
    noise: 'bg-signal-down',
    unproven: 'bg-signal-flat'
  };
  const STAMP: Record<TrustGrade, { cls: string; text: string }> = {
    trusted: { cls: 'pill-up', text: 'trusted' },
    noise: { cls: 'pill-down', text: 'noise' },
    unproven: { cls: 'pill-flat', text: 'unproven' }
  };

  const COUNT_WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
  const heading = $derived(
    rows.length === 1
      ? 'One signal walks toward the 55% line'
      : `${COUNT_WORDS[rows.length] ?? rows.length} signals walk toward the 55% line`
  );

  // ---------- Epilogue ----------

  const epilogue = $derived.by(() => {
    const noisy = rows.filter((r) => r.grade === 'noise');
    if (noisy.length === 0) {
      return 'No signal currently grades noise. The thresholds below do the judging either way.';
    }
    const named = noisy
      .map((r) => `${r.label.toLowerCase()} graded noise — ${Math.round(r.gross)}% hit over ${r.n} evaluated`)
      .join('; ');
    return `${named[0].toUpperCase()}${named.slice(1)}. The stamp is computed, not curated: if the number recovers, the verdict changes by itself.`;
  });

  let revealed = $state(false);

  // One-shot reveal; under reduced motion the card is simply there.
  function reveal(node: HTMLElement) {
    if (reduced) {
      revealed = true;
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          revealed = true;
          io.disconnect();
        }
      },
      { threshold: 0.2 }
    );
    io.observe(node);
    return { destroy: () => io.disconnect() };
  }
</script>

{#snippet stage(f: TrialFrame, pinned: boolean)}
  <div class="mb-6 flex items-start justify-between gap-3">
    <div>
      <div class="text-[10px] uppercase tracking-wider text-zinc-500">signal scoreboard · the trial</div>
      <h2 class="mt-1 text-sm font-semibold tracking-tight">{heading}</h2>
      <p class="mt-1 text-xs text-zinc-500">
        Verdicts are computed by the same thresholds as the table below — nothing here is written by hand.
      </p>
    </div>
    {#if pinned}
      <a href="#scoreboard" class="shrink-0 text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300">
        skip to the table ↓
      </a>
    {/if}
  </div>

  {#if hasNet}
    <!-- space is reserved from p=0 so the fade-in never shifts the bars -->
    <div class="mb-3" style="opacity: {f.chip}">
      <span class="pill pill-warn">−0.5% round-trip slippage</span>
    </div>
  {/if}

  <div class="relative pt-10">
    <!-- shared threshold overlay — on stage before any bar moves -->
    <div class="pointer-events-none absolute bottom-0 left-[6.25rem] right-[4rem] top-0 sm:left-[8.75rem] sm:right-[4.25rem]">
      <div class="absolute bottom-0 top-8 border-l border-dashed border-ink-600" style="left: {NOISE_X}%"></div>
      <div class="absolute bottom-0 top-4 border-l border-dashed border-ink-600" style="left: {TRUST_X}%"></div>
      <span
        class="absolute top-0 -translate-x-full whitespace-nowrap pr-1.5 text-[10px] uppercase tracking-wider text-zinc-500"
        style="left: {TRUST_X}%">trusted ≥ 55 · n ≥ 30</span
      >
      <span
        class="absolute top-4 -translate-x-full whitespace-nowrap pr-1.5 text-[10px] uppercase tracking-wider text-zinc-500"
        style="left: {NOISE_X}%">noise &lt; 45</span
      >
    </div>

    <div class="grid grid-cols-[5.5rem_1fr_3.25rem] items-center gap-x-3 gap-y-5 sm:grid-cols-[8rem_1fr_3.5rem]">
      {#each rows as row, i (row.type)}
        {@const fr = f.rows[i]}
        <div class="text-[10px] uppercase leading-tight tracking-wider text-zinc-500">{row.label}</div>
        <div class="relative h-2 rounded bg-ink-700/60">
          <div
            class="absolute inset-y-0 left-0 rounded transition-colors duration-200 {fr.stamped
              ? TINT[row.grade]
              : 'bg-signal-flat'}"
            style="width: {fr.fill}%"
          ></div>
          {#if row.net != null && fr.ghostW > 0.01}
            <!-- the slippage-shaved span stays visible as a hatched ghost -->
            <div class="trial-ghost absolute inset-y-0 rounded-r" style="left: {fr.fill}%; width: {fr.ghostW}%"></div>
          {/if}
          <!-- verdict stamp -->
          <div
            class="pointer-events-none absolute left-2 top-1/2 z-10 flex -translate-y-1/2 items-center gap-1.5 transition duration-200 {fr.stamped
              ? '-rotate-2 opacity-100'
              : 'rotate-2 scale-110 opacity-0'}"
          >
            <span class="inline-flex rounded bg-ink-900"><span class="pill {STAMP[row.grade].cls}">{STAMP[row.grade].text}</span></span>
            <span class="rounded bg-ink-900/85 px-1 py-px text-[10px] text-zinc-500">n={row.n}</span>
          </div>
        </div>
        <div class="num text-right text-xs text-zinc-300">{fr.value.toFixed(1)}%</div>
      {/each}
    </div>
  </div>
{/snippet}

{#if rows.length > 0}
  {#if !reduced}
    <!-- tall track: the sticky stage pins while progress scrubs 0..1;
         final 5% is at rest so the un-pin into the table feels settled -->
    <div class="relative h-[220vh] sm:h-[250vh]" use:attach>
      <div class="sticky top-0 flex h-[100svh] flex-col items-center justify-center pb-20 sm:pb-0">
        <div class="w-full max-w-2xl">
          {@render stage(frame(sc.progress), true)}
        </div>
      </div>
    </div>
  {:else}
    <!-- reduced motion: the final frame as a plain block — an honest bar chart -->
    <section class="mb-8">
      <div class="w-full max-w-2xl">
        {@render stage(frame(1), false)}
      </div>
    </section>
  {/if}

  <div class="trial-reveal card mb-8 p-4 text-xs text-zinc-400" class:trial-in={revealed} use:reveal>
    {epilogue}
  </div>
{/if}

<style>
  .trial-ghost {
    background-image: repeating-linear-gradient(
      135deg,
      rgb(var(--signal-warn) / 0.25),
      rgb(var(--signal-warn) / 0.25) 3px,
      transparent 3px,
      transparent 6px
    );
  }

  .trial-reveal {
    opacity: 0;
    transform: translateY(0.5rem);
    transition:
      opacity 0.2s ease-out,
      transform 0.2s ease-out;
  }
  .trial-in {
    opacity: 1;
    transform: none;
  }
  @media (prefers-reduced-motion: reduce) {
    .trial-reveal {
      transition: none;
    }
  }
</style>
