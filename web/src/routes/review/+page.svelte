<script lang="ts">
  import { fmtPct, fmtPrice, fmtRelative, pctClass, confidencePill } from '$lib/format';
  import { signalTrust, bandTrust, scoreInverted, GRADE_CLASS, type SignalTrust } from '$lib/trust';
  import TrustTrial from './TrustTrial.svelte';
  import type {
    AlertTypeStats,
    LedgerEntry,
    LedgerStatus,
    WeeklyClassification,
    WeeklyPrediction,
    WeeklyTickerEntry
  } from '$lib/types';

  let { data } = $props();

  // data.review is a streamed promise (see +page.ts) so the page shell renders
  // instantly. Start empty — every section below already has a graceful "no
  // data yet" state — then fill in once the JSON lands.
  let resolved = $state<Awaited<typeof data.review> | null>(null);
  $effect(() => {
    data.review.then((r) => {
      resolved = r;
    });
  });

  const weekly = $derived(resolved?.weekly ?? null);
  const perf = $derived(resolved?.perf ?? null);
  const recPerf = $derived(resolved?.recPerf ?? null);
  const deskPerf = $derived(resolved?.deskPerf ?? null);
  const predPerf = $derived(resolved?.predPerf ?? null);
  const ledger = $derived(resolved?.ledger ?? null);

  // ---------- This week ----------

  function classBadge(c: WeeklyClassification): string {
    switch (c) {
      case 'real_momentum':
        return 'pill-up';
      case 'fakeout':
        return 'pill-down';
      default:
        return 'pill-flat';
    }
  }

  function predBadge(p: WeeklyPrediction): string {
    switch (p) {
      case 'continuation':
        return 'pill-up';
      case 'reversal':
        return 'pill-down';
      default:
        return 'pill-flat';
    }
  }

  const byClass = $derived.by(() => {
    if (!weekly) return { real: [], fake: [], unclear: [] };
    const pick = (c: WeeklyClassification) =>
      weekly.analyses.filter((a) => (a.analysis?.classification ?? a.heuristic_classification) === c);
    return {
      real: pick('real_momentum'),
      fake: pick('fakeout'),
      unclear: pick('unclear')
    };
  });

  // ---------- Signal scoreboard ----------

  const SIGNAL_LABELS: Record<string, { label: string; emoji: string }> = {
    catalyst: { label: 'Catalyst', emoji: '🎯' },
    big_move: { label: 'Big move', emoji: '🚀' },
    watchlist: { label: 'Watchlist', emoji: '⭐' },
    delta_new_top20: { label: 'New top-20', emoji: '📈' },
    serenity_match: { label: 'Serenity match', emoji: '🧠' },
    ripple: { label: 'Ripple', emoji: '🔮' },
    macro: { label: 'Macro', emoji: '🌍' },
    delta_rank_jump: { label: 'Rank jump', emoji: '⚡' },
    delta_accel: { label: 'Accel', emoji: '🌡️' },
    weekly: { label: 'Weekly', emoji: '📊' }
  };

  const SIGNAL_ORDER = ['catalyst', 'big_move', 'watchlist', 'delta_new_top20', 'serenity_match', 'ripple'];
  const REC_BUCKET_ORDER = ['long_hi', 'long_lo', 'short_hi', 'short_lo'];

  function bucketLabel(key: string, highScore: number): { label: string; emoji: string } {
    const [dir, band] = key.split('_');
    const dirLabel = dir === 'long' ? 'Long picks' : 'Short picks';
    const emoji = dir === 'long' ? '📈' : '📉';
    const bandLabel = band === 'hi' ? `score ${highScore}+` : `score under ${highScore}`;
    return { label: `${dirLabel} · ${bandLabel}`, emoji };
  }

  interface ScoreRow {
    key: string;
    label: string;
    emoji: string;
    stats: AlertTypeStats;
    trust: SignalTrust | null;
    gradedAt: '1d' | '5d';
  }

  const scoreRows = $derived.by(() => {
    const out: ScoreRow[] = [];
    if (perf?.per_type) {
      const seen = new Set<string>();
      for (const type of SIGNAL_ORDER) {
        const stats = perf.per_type[type];
        if (!stats) continue;
        seen.add(type);
        const meta = SIGNAL_LABELS[type] ?? { label: type, emoji: '•' };
        out.push({ key: `sig_${type}`, ...meta, stats, trust: signalTrust(perf, type, '1d'), gradedAt: '1d' });
      }
      // Anything new the pipeline starts logging shows up instead of vanishing.
      for (const [type, stats] of Object.entries(perf.per_type)) {
        if (seen.has(type)) continue;
        const meta = SIGNAL_LABELS[type] ?? { label: type, emoji: '•' };
        out.push({ key: `sig_${type}`, ...meta, stats, trust: signalTrust(perf, type, '1d'), gradedAt: '1d' });
      }
    }
    if (recPerf?.per_bucket) {
      const hs = recPerf.high_score ?? 7;
      for (const key of REC_BUCKET_ORDER) {
        const stats = recPerf.per_bucket[key];
        if (!stats) continue;
        const [dir] = key.split('_');
        const meta = bucketLabel(key, hs);
        out.push({
          key: `rec_${key}`,
          ...meta,
          stats,
          trust: bandTrust(recPerf, dir as 'long' | 'short', key.endsWith('_hi') ? hs : 0, '5d'),
          gradedAt: '5d'
        });
      }
    }
    return out;
  });

  const trustedCount = $derived(scoreRows.filter((r) => r.trust?.grade === 'trusted').length);

  // Plain-language verdicts from the trust grades (thresholds live in lib/trust.ts:
  // trusted = n>=30 and >=55% hit; noise = n>=30 and <45%; everything else unproven).
  function verdictFor(t: SignalTrust | null): { text: string; cls: string } {
    if (!t || t.hitRate == null || t.n === 0) {
      return { text: 'no outcomes yet — too new to grade', cls: 'text-zinc-500' };
    }
    if (t.grade === 'trusted') {
      return {
        text: trustedCount === 1 ? 'trusted — the one signal worth acting on' : 'trusted — worth acting on',
        cls: GRADE_CLASS.trusted
      };
    }
    if (t.grade === 'noise') {
      return {
        text:
          t.avgReturn != null && t.avgReturn < 0
            ? 'losing money — candidate for kill'
            : 'noise — below coin-flip',
        cls: GRADE_CLASS.noise
      };
    }
    if (t.n < 30) return { text: `unproven — small sample (n=${t.n})`, cls: GRADE_CLASS.unproven };
    return { text: 'coin-flip — no edge either way', cls: GRADE_CLASS.unproven };
  }

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

  // ---------- Calibration ----------

  type Tone = 'good' | 'bad' | 'flat';
  interface CalLine {
    text: string;
    tone: Tone;
  }
  const TONE_CLASS: Record<Tone, string> = {
    good: 'text-signal-up',
    bad: 'text-signal-down',
    flat: 'text-zinc-400'
  };
  const TONE_DOT: Record<Tone, string> = {
    good: 'bg-signal-up',
    bad: 'bg-signal-down',
    flat: 'bg-zinc-500'
  };

  const calibration = $derived.by(() => {
    const lines: CalLine[] = [];

    // (a) Is the conviction score inverted?
    if (recPerf && scoreInverted(recPerf, 'long')) {
      const hs = recPerf.high_score ?? 7;
      lines.push({
        text: `score ${hs}+ longs underperform sub-${hs} longs — treat the conviction number as decoration until this flips`,
        tone: 'bad'
      });
    }

    // (b) Does prediction confidence mean anything? (5d horizon, n>=10 per side)
    const hi = predPerf?.by_confidence?.high?.horizons?.['5d'];
    const lo = predPerf?.by_confidence?.low?.horizons?.['5d'];
    if (
      hi?.hit_rate != null &&
      lo?.hit_rate != null &&
      (hi.evaluated ?? 0) >= 10 &&
      (lo.evaluated ?? 0) >= 10
    ) {
      const hiPct = hi.hit_rate * 100;
      const loPct = lo.hit_rate * 100;
      if (hiPct > loPct + 5) {
        lines.push({
          text: `prediction confidence is informative — high-confidence calls hit ${Math.round(hiPct)}% vs ${Math.round(loPct)}% for low (5d)`,
          tone: 'good'
        });
      } else {
        lines.push({
          text: `prediction confidence is currently uninformative — high hits ${Math.round(hiPct)}% vs ${Math.round(loPct)}% for low (5d)`,
          tone: 'flat'
        });
      }
    }

    // (c) Does the agent desk add value?
    if (deskPerf && deskPerf.total_with_desk > 0) {
      let deskLine: CalLine | null = null;
      for (const h of ['5d', '3d', '1d']) {
        const v = deskPerf.take_minus_pass_edge?.[h];
        if (v == null) continue;
        if (v > 0) {
          deskLine = { text: `the desk adds value — take beats pass by +${v.toFixed(2)}% at ${h}`, tone: 'good' };
        } else if (v < 0) {
          deskLine = { text: `the desk subtracts value — take trails pass by ${v.toFixed(2)}% at ${h}`, tone: 'bad' };
        } else {
          deskLine = { text: `desk edge is flat — take ≈ pass at ${h}`, tone: 'flat' };
        }
        break;
      }
      lines.push(
        deskLine ?? { text: 'desk verdicts logged but none evaluated yet — edge unknown', tone: 'flat' }
      );
    } else {
      lines.push({ text: 'desk has no evaluated verdicts yet — edge unknown', tone: 'flat' });
    }

    // (d) Calls pushed without a logged entry price.
    if (predPerf?.untracked_count) {
      lines.push({
        text: `${predPerf.untracked_count} pushed call${predPerf.untracked_count === 1 ? '' : 's'} currently untracked — no entry price was logged`,
        tone: 'bad'
      });
    }

    return lines;
  });

  // ---------- Ledger ----------

  const LEDGER_CAP = 100;

  const ledgerEntries = $derived.by(() => {
    if (!ledger?.entries?.length) return [] as LedgerEntry[];
    return [...ledger.entries]
      .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())
      .slice(0, LEDGER_CAP);
  });

  const STATUS_PILL: Record<LedgerStatus, string> = {
    pending: 'pill-flat',
    hit: 'pill-up',
    miss: 'pill-down',
    untracked: 'pill-warn'
  };

  function ledgerChip(e: LedgerEntry): string {
    return e.type && e.type !== e.kind ? `${e.kind} · ${e.type.replace(/_/g, ' ')}` : e.kind;
  }
</script>

<svelte:head>
  <title>Momentum — review</title>
</svelte:head>

<header class="mb-6">
  <h1 class="font-display text-2xl font-black tracking-tight">Review</h1>
  <p class="text-xs text-zinc-500">
    What we said vs what happened — the weekly read-through on top, the signal track record and
    the call ledger underneath.
  </p>
</header>

<!-- 1 · This week -->
<section class="mb-8">
  <header class="mb-3 flex items-center justify-between">
    <h2 class="text-sm font-semibold tracking-tight">This week</h2>
    <span class="text-[10px] uppercase tracking-wider text-zinc-500">
      real vs fakeout + forward predictions · runs Saturdays
    </span>
  </header>

  {#if !weekly || weekly.analyses.length === 0}
    <p class="card p-4 text-xs text-zinc-500">
      No weekly summary yet — the Saturday workflow writes this (or trigger "Weekly summary" manually
      from the Actions tab).
    </p>
  {:else}
    <div class="mb-3 flex flex-wrap items-center gap-2 text-xs">
      <span class="pill pill-up">real momentum · {byClass.real.length}</span>
      <span class="pill pill-down">fakeouts · {byClass.fake.length}</span>
      <span class="pill pill-flat">unclear · {byClass.unclear.length}</span>
      <span class="ml-auto text-zinc-500">
        week ending {weekly.week_ending} · generated {fmtRelative(weekly.generated_at)}
      </span>
    </div>

    {#snippet entry(a: WeeklyTickerEntry)}
      {@const analysis = a.analysis}
      {@const cls = analysis?.classification ?? a.heuristic_classification}
      <article class="card mb-3 p-4">
        <header class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <div class="flex flex-wrap items-baseline gap-2">
            <a href={`/t/${a.ticker}`} class="text-xl font-semibold hover:text-signal-info">{a.ticker}</a>
            <span class="pill {classBadge(cls)}">{cls.replace('_', ' ')}</span>
            {#if analysis}
              <span class="pill {predBadge(analysis.prediction)}">{analysis.prediction}</span>
              <span class="pill {confidencePill(analysis.prediction_confidence)}">conf · {analysis.prediction_confidence}</span>
            {/if}
          </div>
          <div class="flex gap-3 text-xs">
            <span class="text-zinc-500">week</span>
            <span class="num font-medium {pctClass(a.metrics.week_return_pct)}">
              {fmtPct(a.metrics.week_return_pct)}
            </span>
            <span class="text-zinc-500">events {a.event_count}</span>
          </div>
        </header>

        {#if analysis?.classification_reasoning}
          <p class="mb-3 text-sm leading-relaxed text-zinc-300">
            <span class="text-[10px] uppercase tracking-wider text-zinc-500">what happened: </span>
            {analysis.classification_reasoning}
          </p>
        {/if}

        {#if analysis?.prediction_rationale}
          <p class="mb-3 text-sm leading-relaxed text-zinc-300">
            <span class="text-[10px] uppercase tracking-wider text-zinc-500">next 1-4 weeks: </span>
            {analysis.prediction_rationale}
          </p>
        {/if}

        <div class="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">Retention</div>
            <div class="num">{(a.metrics.retention_of_peak * 100).toFixed(0)}%</div>
          </div>
          <div>
            <div class="text-[10px] uppercase tracking-wider text-zinc-500">Vol persistence</div>
            <div class="num">{(a.metrics.vol_persistence * 100).toFixed(0)}%</div>
          </div>
          {#if analysis?.support_level}
            <div>
              <div class="text-[10px] uppercase tracking-wider text-zinc-500">Support</div>
              <div class="num">${fmtPrice(analysis.support_level)}</div>
            </div>
          {/if}
          {#if analysis?.resistance_level}
            <div>
              <div class="text-[10px] uppercase tracking-wider text-zinc-500">Resistance</div>
              <div class="num">${fmtPrice(analysis.resistance_level)}</div>
            </div>
          {/if}
        </div>

        {#if analysis?.catalysts_ahead?.length}
          <div class="mt-3 border-t border-ink-700/60 pt-2">
            <div class="mb-1 text-[10px] uppercase tracking-wider text-zinc-500">Catalysts ahead</div>
            <ul class="text-xs text-zinc-300">
              {#each analysis.catalysts_ahead as c}
                <li>· {c}</li>
              {/each}
            </ul>
          </div>
        {/if}
      </article>
    {/snippet}

    {#if byClass.real.length > 0}
      <h3 class="mb-2 text-[10px] font-semibold uppercase tracking-wider text-signal-up">Real momentum</h3>
      {#each byClass.real as a (a.ticker)}
        {@render entry(a)}
      {/each}
    {/if}

    {#if byClass.fake.length > 0}
      <h3 class="mb-2 mt-4 text-[10px] font-semibold uppercase tracking-wider text-signal-down">Fakeouts</h3>
      {#each byClass.fake as a (a.ticker)}
        {@render entry(a)}
      {/each}
    {/if}

    {#if byClass.unclear.length > 0}
      <h3 class="mb-2 mt-4 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Unclear</h3>
      {#each byClass.unclear as a (a.ticker)}
        {@render entry(a)}
      {/each}
    {/if}
  {/if}
</section>

<TrustTrial {perf} />

<!-- 2 · Signal scoreboard -->
<section id="scoreboard" class="mb-8 scroll-mt-4">
  <header class="mb-3 flex items-center justify-between">
    <h2 class="text-sm font-semibold tracking-tight">Signal scoreboard</h2>
    <span class="text-[10px] uppercase tracking-wider text-zinc-500">
      {#if perf || recPerf}
        {perf ? `${perf.total_alerts} alerts` : ''}{perf && recPerf ? ' · ' : ''}{recPerf
          ? `${recPerf.total_picks} picks`
          : ''} · last {(perf ?? recPerf)?.window_days}d
      {:else}
        every signal class, one table
      {/if}
    </span>
  </header>

  {#if scoreRows.length === 0}
    <p class="card p-4 text-xs text-zinc-500">
      No performance data yet — stats accumulate as alerts and picks age past their 1/3/5-day horizons.
    </p>
  {:else}
    <div class="card overflow-x-auto">
      <table class="w-full min-w-[640px] text-xs">
        <thead class="bg-ink-800/40 text-[10px] uppercase tracking-wider text-zinc-500">
          <tr>
            <th class="px-3 py-2 text-left">Signal</th>
            <th class="px-3 py-2 text-left">Verdict</th>
            <th class="px-3 py-2 text-right">Fired</th>
            <th class="px-3 py-2 text-right">1d hit</th>
            <th class="px-3 py-2 text-right">1d avg</th>
            <th class="px-3 py-2 text-right">5d hit</th>
            <th class="px-3 py-2 text-right">5d avg</th>
          </tr>
        </thead>
        <tbody>
          {#each scoreRows as row (row.key)}
            {@const v = verdictFor(row.trust)}
            <tr class="border-t border-ink-700/40">
              <td class="whitespace-nowrap px-3 py-2">
                <span class="mr-1">{row.emoji}</span>
                <span class="font-medium">{row.label}</span>
              </td>
              <td class="min-w-[180px] px-3 py-2 {v.cls}">{v.text}</td>
              <td class="num px-3 py-2 text-right text-zinc-400">{row.stats.count}</td>
              {#each ['1d', '5d'] as h}
                {@const hs = row.stats.horizons[h as '1d' | '5d']}
                <td class="num px-3 py-2 text-right {hitClass(hs?.hit_rate ?? null)}">
                  {hs?.hit_rate != null ? `${(hs.hit_rate * 100).toFixed(0)}%` : '—'}
                  {#if hs?.evaluated != null}
                    <span class="text-[10px] text-zinc-600"> ({hs.evaluated})</span>
                  {/if}
                  {#if hs?.hit_rate_net != null}
                    <div class="text-[10px] text-zinc-600">net {(hs.hit_rate_net * 100).toFixed(0)}%</div>
                  {/if}
                </td>
                <td class="num px-3 py-2 text-right {returnClass(hs?.avg_return_pct ?? null)}">
                  {hs?.avg_return_pct != null ? fmtPct(hs.avg_return_pct) : '—'}
                  {#if hs?.avg_return_net_pct != null}
                    <div class="text-[10px] text-zinc-600">net {fmtPct(hs.avg_return_net_pct)}</div>
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<!-- 3 · Calibration -->
<section class="mb-8">
  <header class="mb-3 flex items-center justify-between">
    <h2 class="text-sm font-semibold tracking-tight">Calibration</h2>
    <span class="text-[10px] uppercase tracking-wider text-zinc-500">
      do the confidence knobs mean anything
    </span>
  </header>

  {#if calibration.length === 0}
    <p class="card p-4 text-xs text-zinc-500">
      Not enough evaluated outcomes to compute calibration verdicts yet.
    </p>
  {:else}
    <div class="card divide-y divide-ink-700/40">
      {#each calibration as line}
        <p class="flex items-baseline gap-2 px-4 py-2.5 text-sm leading-relaxed {TONE_CLASS[line.tone]}">
          <span class="inline-block h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full {TONE_DOT[line.tone]}"></span>
          {line.text}
        </p>
      {/each}
    </div>
  {/if}
</section>

<!-- 4 · Ledger -->
<section class="mb-8">
  <header class="mb-3 flex items-center justify-between">
    <h2 class="text-sm font-semibold tracking-tight">Ledger</h2>
    <span class="text-[10px] uppercase tracking-wider text-zinc-500">
      every dispatched call and what happened next
    </span>
  </header>

  {#if !ledger}
    <p class="card p-4 text-xs text-zinc-500">ledger lands with the next pipeline deploy</p>
  {:else if ledgerEntries.length === 0}
    <p class="card p-4 text-xs text-zinc-500">Ledger is live but has no entries yet.</p>
  {:else}
    <div class="mb-2 text-[10px] uppercase tracking-wider text-zinc-500">
      {#if ledger.entries.length > LEDGER_CAP}
        showing latest {LEDGER_CAP} of {ledger.entries.length} entries
      {:else}
        {ledger.entries.length} entries
      {/if}
      · last {ledger.window_days}d · updated {fmtRelative(ledger.generated_at)}
    </div>
    <div class="card overflow-x-auto">
      <table class="w-full min-w-[760px] text-xs">
        <thead class="bg-ink-800/40 text-[10px] uppercase tracking-wider text-zinc-500">
          <tr>
            <th class="px-3 py-2 text-left">When</th>
            <th class="px-3 py-2 text-left">Signal</th>
            <th class="px-3 py-2 text-left">Ticker</th>
            <th class="px-3 py-2 text-left">Dir</th>
            <th class="px-3 py-2 text-left">Thesis</th>
            <th class="px-3 py-2 text-right">1d</th>
            <th class="px-3 py-2 text-right">3d</th>
            <th class="px-3 py-2 text-right">5d</th>
            <th class="px-3 py-2 text-left">Status</th>
          </tr>
        </thead>
        <tbody>
          {#each ledgerEntries as e (e.id)}
            <tr class="border-t border-ink-700/40">
              <td class="whitespace-nowrap px-3 py-2 text-zinc-500">{fmtRelative(e.ts)}</td>
              <td class="whitespace-nowrap px-3 py-2">
                <span class="pill-flat">{ledgerChip(e)}</span>
              </td>
              <td class="px-3 py-2">
                <a href={`/t/${e.ticker}`} class="font-mono font-semibold hover:text-signal-info">{e.ticker}</a>
              </td>
              <td class="px-3 py-2">
                {#if e.direction === 'long'}
                  <span class="text-signal-up">↑</span>
                {:else if e.direction === 'short'}
                  <span class="text-signal-down">↓</span>
                {:else}
                  <span class="text-zinc-600">–</span>
                {/if}
              </td>
              <td class="max-w-[280px] truncate px-3 py-2 text-zinc-400" title={e.thesis}>{e.thesis}</td>
              {#each ['1d', '3d', '5d'] as h}
                {@const o = e.outcomes?.[h as '1d' | '3d' | '5d'] ?? null}
                <td class="num px-3 py-2 text-right {pctClass(o)}">
                  {o != null ? fmtPct(o) : '–'}
                </td>
              {/each}
              <td class="px-3 py-2">
                <span class={STATUS_PILL[e.status] ?? 'pill-flat'}>{e.status}</span>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<!-- 5 · Methodology -->
<footer class="space-y-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
  <p>
    Hit = the signal's directional call followed through (positive signed return after N days).
    Counts in parentheses show how many entries have actually reached that horizon. Returns are
    gross of costs; where a net line appears it is after the 0.5% round-trip slippage drag.
  </p>
  <p>
    Signal rows are graded at the 1-day horizon, pick buckets at 5-day. Trusted needs n≥30 and a
    ≥55% hit rate; noise is &lt;45% on a real sample; everything else — including brand-new signals
    — is unproven, not endorsed.
  </p>
  <p>
    If the conviction score is predictive, the score {recPerf?.high_score ?? 7}+ rows should beat
    the under-{recPerf?.high_score ?? 7} rows. If the desk's take ≈ pass, the agents aren't adding
    signal — that's the cue to cut the desk's per-scan cost.
  </p>
  {#if predPerf?.horizon_note}
    <p>{predPerf.horizon_note}</p>
  {/if}
</footer>
