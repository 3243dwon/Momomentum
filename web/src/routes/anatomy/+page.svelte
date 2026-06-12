<script lang="ts">
  import { Scrub, phase, prefersReducedMotion } from '$lib/scrub.svelte';
  import {
    AFTERMATH_CLOSES,
    BEATS,
    FAILED_DISPATCH,
    LEDGER_ENTRY,
    MAX_STANDARD_ALERTS_PER_SCAN,
    NEWS,
    PRIORITY_LADDER,
    SCAN,
    type Beat
  } from './story';

  // One real alert (SRAD, 2026-06-08) replayed as six scroll-driven beats.
  // Every visual is a pure function of Scrub progress, so the scene plays
  // forward and backward; reduced-motion gets the same story as a static
  // article instead of a pinned track.
  const sc = new Scrub();
  const attach = sc.attach;
  const reduced = prefersReducedMotion();

  const p = $derived(sc.progress);
  const ph = (a: number, b: number) => phase(p, a, b);

  const TITLES = [
    `${SCAN.universe_size.toLocaleString('en-US')} tickers. One headline.`,
    'Classified.',
    'The cut.',
    'Dispatch.',
    'The tape.',
    'Verdict.'
  ];

  // ---------- Beat windows (crossfades ±0.02 around the band edges) ----------

  const wA = $derived(1 - ph(0.5, 0.54)); // headline card · beats 1-3
  const wB = $derived(ph(0.5, 0.54) * (1 - ph(0.68, 0.72))); // dispatch · beat 4
  const wC = $derived(ph(0.68, 0.72) * (1 - ph(0.86, 0.9))); // tape · beat 5
  const wD = $derived(ph(0.86, 0.9)); // verdict · beat 6
  const wLadder = $derived(ph(0.16, 0.2) * (1 - ph(0.36, 0.4)));
  const wCut = $derived(ph(0.38, 0.42) * (1 - ph(0.49, 0.53)));
  const backdropO = $derived(ph(0.36, 0.4) * (1 - ph(0.47, 0.52)));
  const backdropScale = $derived(1 - 0.8 * ph(0.38, 0.52));
  const titleW = $derived([
    1 - ph(0.14, 0.18),
    ph(0.14, 0.18) * (1 - ph(0.34, 0.38)),
    ph(0.34, 0.38) * (1 - ph(0.5, 0.54)),
    wB,
    wC,
    wD
  ]);

  // ---------- Frozen-data plumbing ----------

  const LEDGER_JSON = JSON.stringify(LEDGER_ENTRY, null, 2);
  const WHEN = LEDGER_ENTRY.ts.slice(0, 16).replace('T', ' ') + ' UTC'; // 2026-06-08 19:23 UTC
  const PUSHED_AT = LEDGER_ENTRY.ts.slice(11, 19) + ' UTC'; // 19:23:04 UTC
  const ONE_D = LEDGER_ENTRY.outcomes['1d'];

  // ---------- Discrete triggers + continuous scrubs ----------

  const typedChars = $derived(Math.round(ph(0.04, 0.14) * NEWS.title.length));
  const pillStep = $derived(p >= 0.285 ? 4 : p >= 0.25 ? 3 : p >= 0.215 ? 2 : p >= 0.18 ? 1 : 0);
  const markerT = $derived(ph(0.2, 0.3));
  const jsonChars = $derived(Math.round(ph(0.545, 0.655) * LEDGER_JSON.length));
  const pushed = $derived(p >= 0.66);
  const drawT = $derived(ph(0.72, 0.86));
  const hit = $derived(p >= 0.94);

  const beat = $derived.by(() => {
    let cur: Beat = BEATS[0];
    for (const b of BEATS) if (p >= b.a) cur = b;
    return cur;
  });

  const BIG_MOVE_IDX = PRIORITY_LADDER.findIndex((r) => r.type === 'big_move');
  const ROW_H = 28; // h-7 ladder rows

  // 718-row backdrop: a 1px repeating gradient, not 718 DOM nodes.
  const ROWS_PATTERN =
    'repeating-linear-gradient(to bottom, rgb(var(--ink-700) / 0.6) 0px, rgb(var(--ink-700) / 0.6) 1px, transparent 1px, transparent 9px)';

  // ---------- Tape chart (PriceChart geometry: hand-rolled SVG) ----------

  const VALUES = [...SCAN.srad.spark, ...AFTERMATH_CLOSES];
  const W = 340;
  const H = 150;
  const PAD_R = 52; // room for the entry label
  const PAD_Y = 8;

  const lo = Math.min(...VALUES, LEDGER_ENTRY.price);
  const hi = Math.max(...VALUES, LEDGER_ENTRY.price);
  const pad = (hi - lo) * 0.06;
  const yOf = (v: number) => PAD_Y + (1 - (v - (lo - pad)) / (hi + pad - (lo - pad))) * (H - 2 * PAD_Y);

  const xStep = (W - PAD_R) / (VALUES.length - 1);
  const linePath = VALUES.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * xStep).toFixed(1)},${yOf(v).toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L${((VALUES.length - 1) * xStep).toFixed(1)},${H} L0,${H} Z`;

  const ALERT_I = SCAN.srad.spark.length - 1; // the alert fired on the last spark close
  // +1d = the first close AFTER the entry session: AFTERMATH_CLOSES[0] is the
  // entry day's own close (the entry was intraday), [1] is what the ledger
  // graded (15.12 -> 16.40 = +8.47%).
  const GATE_I = ALERT_I + 2;
  const alertX = ALERT_I * xStep;
  const gateX = GATE_I * xStep;
  const gateY = yOf(VALUES[GATE_I]);
  const entryY = yOf(LEDGER_ENTRY.price);
  const GATE_FRAC = GATE_I / (VALUES.length - 1); // when the drawn line crosses the gate
</script>

<svelte:head>
  <title>Momentum — anatomy of an alert</title>
</svelte:head>

<h1 class="sr-only">Anatomy of an alert</h1>

<!-- ---------- Shared beat pieces (rendered by both the pinned scene and the
     reduced-motion article) ---------- -->

{#snippet beatTag(b: Beat)}
  <div class="text-[10px] uppercase tracking-wider text-zinc-500">
    beat {String(b.n).padStart(2, '0')} · {b.label}
  </div>
{/snippet}

{#snippet beatTitle(i: number)}
  <h2 class="font-display text-3xl font-bold leading-tight sm:text-5xl sm:font-black">{TITLES[i]}</h2>
{/snippet}

{#snippet headlineInner(chars: number, pills: number)}
  <p class="min-h-[2.5rem] text-sm leading-relaxed text-zinc-100 sm:text-base">
    {NEWS.title.slice(0, chars)}{#if chars > 0 && chars < NEWS.title.length}<span class="text-signal-info">▌</span>{/if}
  </p>
  <div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] uppercase tracking-wider text-zinc-500">
    <span>{NEWS.publisher} via {NEWS.source}</span>
    <span>·</span>
    <span>{NEWS.type}</span>
    <span>·</span>
    <span>impact {NEWS.impact}</span>
    <span>·</span>
    <span class="num">${NEWS.ticker}</span>
  </div>
  {#if !reduced || pills > 0}
    <div class="mt-3 flex flex-wrap gap-1.5">
      <span class="pill-up pop" class:on={pills >= 1}>catalyst</span>
      <span class="pill-warn pop" class:on={pills >= 2}>impact high</span>
      <span class="pill-info pop" class:on={pills >= 3}>+{SCAN.srad.pct_1d}% on {SCAN.srad.rel_volume}x vol</span>
      <span class="pill-flat pop" class:on={pills >= 4}>news explains move</span>
    </div>
  {/if}
{/snippet}

{#snippet ladderInner(t: number)}
  {@const markerRow = Math.round(BIG_MOVE_IDX * (1 - t))}
  <div class="relative border-l border-ink-700">
    <div
      class="absolute -left-px top-0 h-7 w-0.5 bg-signal-up"
      style="transform: translateY({(BIG_MOVE_IDX * (1 - t) * ROW_H).toFixed(1)}px)"
    ></div>
    {#each PRIORITY_LADDER as rung, i (rung.type)}
      <div class="flex h-7 items-center justify-between gap-3 pl-3 {i === markerRow ? 'text-zinc-100' : 'text-zinc-500'}">
        <span class="text-[10px] uppercase tracking-wider">{rung.type.replace(/_/g, ' ')}</span>
        <span class="num text-[10px]">{rung.priority}</span>
      </div>
    {/each}
  </div>
  <p class="pop mt-2 text-[10px] uppercase leading-relaxed tracking-wider text-zinc-500" class:on={t >= 1}>
    already flagged big_move (60) — the headline promoted it to catalyst (100)
  </p>
{/snippet}

{#snippet cutCaption()}
  <p class="mx-auto max-w-md text-center text-[10px] uppercase leading-relaxed tracking-wider text-zinc-500">
    {SCAN.row_count} rows survived the {SCAN.universe_size.toLocaleString('en-US')}-ticker scan. the
    ladder ranks every would-be alert; a hard cap of {MAX_STANDARD_ALERTS_PER_SCAN} standard alerts
    per scan decides who speaks — catalyst is high-conviction and always fires.
  </p>
{/snippet}

{#snippet dispatchInner(chars: number, sent: boolean)}
  <!-- Invisible full copy keeps the card height stable while the JSON types. -->
  <div class="grid">
    <pre class="num invisible col-start-1 row-start-1 whitespace-pre-wrap text-[11px] leading-relaxed" aria-hidden="true">{LEDGER_JSON}</pre>
    <pre class="num col-start-1 row-start-1 whitespace-pre-wrap text-[11px] leading-relaxed text-zinc-300">{LEDGER_JSON.slice(0, chars)}</pre>
  </div>
  <div class="pop mt-2 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-signal-info" class:on={sent}>
    <span class="relative flex h-1.5 w-1.5">
      <span class="absolute inline-flex h-full w-full rounded-full bg-current opacity-60 motion-safe:animate-ping"></span>
      <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-current"></span>
    </span>
    pushed {PUSHED_AT}
  </div>
{/snippet}

{#snippet failureAside()}
  <aside class="mx-auto max-w-md rounded-lg border border-signal-down/30 bg-signal-down/5 p-3">
    <div class="text-[10px] uppercase tracking-wider text-signal-down">failed dispatch · 2026-06-01 15:20:08 UTC</div>
    <p class="mt-1 text-xs text-zinc-300">“{FAILED_DISPATCH.title}”</p>
    <p class="num mt-0.5 text-[11px] text-signal-down">{FAILED_DISPATCH.error}</p>
    <p class="mt-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
      failures are logged too — the audit trail keeps both.
    </p>
  </aside>
{/snippet}

{#snippet tapeInner(t: number)}
  {@const stamped = t >= GATE_FRAC}
  <svg
    viewBox="0 0 {W} {H}"
    class="w-full"
    role="img"
    aria-label="SRAD 20-day closes into the alert plus four aftermath closes, entry at 15.12"
  >
    <defs>
      <linearGradient id="anatomy-fade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="currentColor" stop-opacity="0.18" />
        <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
      </linearGradient>
    </defs>

    <!-- entry reference -->
    <g class="text-zinc-400">
      <line x1="0" x2={W - PAD_R + 4} y1={entryY} y2={entryY} stroke="currentColor" stroke-width="0.75" stroke-dasharray="2 3" opacity="0.7" />
      <text x={W} y={entryY + 2.5} text-anchor="end" class="num" fill="currentColor" font-size="8" opacity="0.9">ENTRY {LEDGER_ENTRY.price.toFixed(2)}</text>
    </g>

    <!-- the alert moment + the 1d grading gate -->
    <g class="text-zinc-500">
      <line x1={alertX} x2={alertX} y1={PAD_Y} y2={H - PAD_Y} stroke="currentColor" stroke-width="0.75" stroke-dasharray="1 4" opacity="0.8" />
      <text x={alertX} y={PAD_Y - 1} class="num" fill="currentColor" font-size="7" text-anchor="middle">alert</text>
    </g>
    <g class="text-zinc-600">
      <line x1={gateX} x2={gateX} y1={PAD_Y} y2={H - PAD_Y} stroke="currentColor" stroke-width="0.75" stroke-dasharray="4 3" opacity="0.8" />
      <text x={gateX} y={H - 1} class="num" fill="currentColor" font-size="7" text-anchor="middle">+1d</text>
    </g>

    <g class="text-signal-up">
      <path d={areaPath} fill="url(#anatomy-fade)" style="opacity: {t}" />
      <path
        d={linePath}
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linejoin="round"
        stroke-linecap="round"
        pathLength="1"
        stroke-dasharray="1"
        style="stroke-dashoffset: {1 - t}"
      />
      <g class="pop" class:on={stamped}>
        <circle cx={gateX} cy={gateY} r="2.4" fill="currentColor" />
        <text x={gateX + 5} y={gateY - 5} class="num" fill="currentColor" font-size="10" font-weight="600">+{ONE_D}%</text>
      </g>
    </g>
  </svg>
  <p class="mt-2 text-[10px] uppercase tracking-wider text-zinc-500">
    graded at the 1d horizon only — the entry rotated out of the live ledger window before 3d/5d filled.
  </p>
{/snippet}

{#snippet verdictInner(graded: boolean)}
  <div class="overflow-x-auto">
    <table class="w-full min-w-[460px] text-xs">
      <thead class="bg-ink-800/40 text-[10px] uppercase tracking-wider text-zinc-500">
        <tr>
          <th class="px-3 py-2 text-left">When</th>
          <th class="px-3 py-2 text-left">Signal</th>
          <th class="px-3 py-2 text-left">Ticker</th>
          <th class="px-3 py-2 text-left">Dir</th>
          <th class="px-3 py-2 text-right">1d</th>
          <th class="px-3 py-2 text-left">Status</th>
        </tr>
      </thead>
      <tbody>
        <tr class="border-t border-ink-700/40">
          <td class="num whitespace-nowrap px-3 py-2 text-zinc-500">{WHEN}</td>
          <td class="whitespace-nowrap px-3 py-2"><span class="pill-flat">{LEDGER_ENTRY.kind} · {LEDGER_ENTRY.type}</span></td>
          <td class="px-3 py-2">
            <a href={`/t/${LEDGER_ENTRY.ticker}`} class="font-mono font-semibold hover:text-signal-info">{LEDGER_ENTRY.ticker}</a>
          </td>
          <td class="px-3 py-2"><span class="text-signal-up">↑</span></td>
          <td class="num px-3 py-2 text-right text-signal-up">+{ONE_D}%</td>
          <td class="px-3 py-2">
            <span class="grid">
              <span class="pill-flat col-start-1 row-start-1 transition-opacity duration-200" style="opacity: {graded ? 0 : 1}">pending</span>
              <span class="pill-up col-start-1 row-start-1 transition-opacity duration-200" style="opacity: {graded ? 1 : 0}">hit</span>
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
{/snippet}

{#snippet verdictLinks()}
  <div class="flex flex-wrap justify-center gap-x-5 gap-y-1 text-[10px] uppercase tracking-wider">
    <a href="/review#scoreboard" class="text-zinc-500 transition-colors hover:text-zinc-300">the live ledger keeps today’s receipts →</a>
    <a href={`/t/${LEDGER_ENTRY.ticker}`} class="text-zinc-500 transition-colors hover:text-zinc-300">{LEDGER_ENTRY.ticker} now →</a>
  </div>
{/snippet}

{#if reduced}
  <!-- ---------- Reduced motion: the same six beats as a static article ---------- -->
  <article class="mx-auto max-w-2xl">
    <p class="mb-8 text-[10px] uppercase tracking-wider text-zinc-500">
      anatomy of an alert · one real alert, replayed from committed data
    </p>

    <section class="mb-10">
      {@render beatTag(BEATS[0])}
      <div class="mt-1">{@render beatTitle(0)}</div>
      <p class="num mt-2 text-xs text-zinc-500">{SCAN.generated_at}</p>
      <div class="card mt-4 p-4 sm:p-5">{@render headlineInner(NEWS.title.length, 0)}</div>
    </section>

    <section class="mb-10">
      {@render beatTag(BEATS[1])}
      <div class="mt-1">{@render beatTitle(1)}</div>
      <div class="card mt-4 p-4 sm:p-5">{@render headlineInner(NEWS.title.length, 4)}</div>
      <div class="mt-4 max-w-xs">{@render ladderInner(1)}</div>
    </section>

    <section class="mb-10">
      {@render beatTag(BEATS[2])}
      <div class="mt-1">{@render beatTitle(2)}</div>
      <div class="mt-4 h-24 rounded-lg border border-ink-700/60" style="background-image: {ROWS_PATTERN}"></div>
      <div class="mt-4">{@render cutCaption()}</div>
    </section>

    <section class="mb-10">
      {@render beatTag(BEATS[3])}
      <div class="mt-1">{@render beatTitle(3)}</div>
      <div class="card mt-4 p-4 sm:p-5">{@render dispatchInner(LEDGER_JSON.length, true)}</div>
      <div class="mt-4">{@render failureAside()}</div>
    </section>

    <section class="mb-10">
      {@render beatTag(BEATS[4])}
      <div class="mt-1">{@render beatTitle(4)}</div>
      <div class="card mt-4 p-4 sm:p-5">{@render tapeInner(1)}</div>
    </section>

    <section class="mb-10">
      {@render beatTag(BEATS[5])}
      <div class="mt-1">{@render beatTitle(5)}</div>
      <div class="card mt-4 overflow-hidden">{@render verdictInner(true)}</div>
      <div class="mt-4">{@render verdictLinks()}</div>
    </section>
  </article>
{:else}
  <!-- ---------- Pinned scene: ~600vh track, one sticky 100svh stage ---------- -->
  <div use:attach class="relative h-[450svh] sm:h-[600svh]">
    <section class="sticky top-0 flex h-[100svh] flex-col justify-center overflow-hidden pb-20 sm:pb-0">
      <!-- beat 3 backdrop: the 718 scanned rows as a collapsing line pattern -->
      <div
        class="pointer-events-none absolute inset-0"
        style="opacity: {backdropO}; transform: scaleY({backdropScale}); background-image: {ROWS_PATTERN}; -webkit-mask-image: radial-gradient(70% 60% at 50% 50%, black 30%, transparent 100%); mask-image: radial-gradient(70% 60% at 50% 50%, black 30%, transparent 100%)"
      ></div>

      <!-- persistent beat label -->
      <div class="absolute right-0 top-4">{@render beatTag(beat)}</div>

      <div class="relative mx-auto w-full max-w-2xl">
        <!-- Playfair beat titles over the terminal data, crossfaded in place -->
        <div class="mb-5 grid">
          {#each TITLES as _, i (i)}
            <div class="col-start-1 row-start-1 self-end" style="opacity: {titleW[i]}">
              {@render beatTitle(i)}
              {#if i === 0}
                <p class="num mt-2 text-xs text-zinc-500">{SCAN.generated_at}</p>
              {/if}
            </div>
          {/each}
        </div>

        <!-- the persistent card + the beat-2 priority-ladder rail -->
        <div class="flex items-center gap-6">
          <div class="card grid min-w-0 flex-1 p-4 sm:p-5">
            <div class="pointer-events-none col-start-1 row-start-1 self-center" style="opacity: {wA}">
              {@render headlineInner(typedChars, pillStep)}
            </div>
            <div class="pointer-events-none col-start-1 row-start-1 self-center" style="opacity: {wB}">
              {@render dispatchInner(jsonChars, pushed)}
            </div>
            <div class="pointer-events-none col-start-1 row-start-1 self-center" style="opacity: {wC}">
              {@render tapeInner(drawT)}
            </div>
            <div class="col-start-1 row-start-1 self-center" style="opacity: {wD}; pointer-events: {wD > 0.5 ? 'auto' : 'none'}">
              {@render verdictInner(hit)}
            </div>
          </div>
          <aside class="hidden w-52 shrink-0 sm:block" style="opacity: {wLadder}">
            {@render ladderInner(markerT)}
          </aside>
        </div>

        <!-- below-card slot: per-beat captions share one grid cell -->
        <div class="mt-4 grid">
          <div class="pointer-events-none col-start-1 row-start-1 self-start" style="opacity: {wCut}">
            {@render cutCaption()}
          </div>
          <div class="pointer-events-none col-start-1 row-start-1 self-start" style="opacity: {wB}">
            {@render failureAside()}
          </div>
          <div class="col-start-1 row-start-1 self-start" style="opacity: {wD}; pointer-events: {wD > 0.5 ? 'auto' : 'none'}">
            {@render verdictLinks()}
          </div>
        </div>
      </div>

      <!-- entry hint, gone by the first beat's end -->
      <div
        class="pointer-events-none absolute inset-x-0 bottom-24 text-center text-[10px] uppercase tracking-wider text-zinc-600 sm:bottom-6"
        style="opacity: {1 - ph(0.01, 0.05)}"
      >
        scroll
      </div>
    </section>
  </div>
{/if}

<!-- ---------- Methodology: where every number on this page lives ---------- -->
<footer class="mx-auto mt-10 max-w-2xl space-y-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
  <p>
    this page replays one real alert end to end — every number above is frozen from committed
    data; nothing is synthetic.
  </p>
  <p>
    headline: data/news.json · scan row + 20-day spark: data/scan.json (the scan that fired) ·
    graded entry: data/ledger.json (since rotated out of the live window) · failed dispatch:
    data/audit/2026-06-01/ · priority ladder + per-scan cap: scanner/alerts/rules.py.
  </p>
</footer>

<style>
  /* Discrete pops: <=200ms transitions on a p-crossing class toggle, so they
     fire in both scroll directions and collapse to a static final frame. */
  .pop {
    opacity: 0;
    transform: translateY(4px) scale(0.97);
    transition:
      opacity 180ms ease-out,
      transform 180ms ease-out;
  }
  .pop.on {
    opacity: 1;
    transform: none;
  }
  @media (prefers-reduced-motion: reduce) {
    .pop {
      transition: none;
    }
  }
</style>
