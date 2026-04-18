<script lang="ts">
  import { fmtPct, fmtPrice, fmtRelative, fmtClock, confidencePill } from '$lib/format';
  import type { WeeklyClassification, WeeklyPrediction } from '$lib/types';

  let { data } = $props();
  const weekly = data.weekly;

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
      case 'rangebound':
        return 'pill-flat';
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
</script>

<svelte:head>
  <title>Weekly summary — Momentum</title>
</svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">Weekly summary</h1>
  <p class="text-xs text-zinc-500">
    Real vs fakeout classification + Opus forward predictions. Runs Saturday mornings.
  </p>
</header>

{#if !weekly}
  <div class="card p-8 text-center text-zinc-400">
    <p class="text-sm">No weekly summary yet.</p>
    <p class="mt-2 text-xs">
      The Saturday workflow produces this. You can also trigger it manually from
      the Actions tab on GitHub ("Weekly summary" → Run workflow).
    </p>
  </div>
{:else}
  <section class="mb-6 flex flex-wrap items-center gap-2 text-xs">
    <span class="pill pill-up">real momentum · {byClass.real.length}</span>
    <span class="pill pill-down">fakeouts · {byClass.fake.length}</span>
    <span class="pill pill-flat">unclear · {byClass.unclear.length}</span>
    <span class="ml-auto text-zinc-500">
      week ending {weekly.week_ending} · generated {fmtRelative(weekly.generated_at)}
    </span>
  </section>

  {#snippet entry(a: any)}
    {@const analysis = a.analysis}
    {@const cls = analysis?.classification ?? a.heuristic_classification}
    <article class="card mb-3 p-4">
      <header class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div class="flex items-baseline gap-2">
          <a href={`/t/${a.ticker}`} class="text-xl font-semibold hover:text-signal-info">{a.ticker}</a>
          <span class="pill {classBadge(cls)}">{cls.replace('_', ' ')}</span>
          {#if analysis}
            <span class="pill {predBadge(analysis.prediction)}">{analysis.prediction}</span>
            <span class="pill {confidencePill(analysis.prediction_confidence)}">conf · {analysis.prediction_confidence}</span>
          {/if}
        </div>
        <div class="flex gap-3 text-xs">
          <span class="text-zinc-500">week</span>
          <span class="num font-medium {a.metrics.week_return_pct >= 0 ? 'text-signal-up' : 'text-signal-down'}">
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

      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
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
    <section class="mb-6">
      <h2 class="mb-2 text-sm font-semibold text-signal-up">Real momentum</h2>
      {#each byClass.real as a}
        {@render entry(a)}
      {/each}
    </section>
  {/if}

  {#if byClass.fake.length > 0}
    <section class="mb-6">
      <h2 class="mb-2 text-sm font-semibold text-signal-down">Fakeouts</h2>
      {#each byClass.fake as a}
        {@render entry(a)}
      {/each}
    </section>
  {/if}

  {#if byClass.unclear.length > 0}
    <section class="mb-6">
      <h2 class="mb-2 text-sm font-semibold text-zinc-400">Unclear</h2>
      {#each byClass.unclear as a}
        {@render entry(a)}
      {/each}
    </section>
  {/if}
{/if}
