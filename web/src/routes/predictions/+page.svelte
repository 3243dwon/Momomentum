<script lang="ts">
  import { fmtPct, fmtRelative, confidencePill, pricedPill } from '$lib/format';
  import { reveal } from '$lib/reveal.svelte';
  import type {
    DealPrediction,
    PricedIn,
    AlertTypeStats
  } from '$lib/types';

  let { data } = $props();

  const predictions = $derived(data.predictions);
  const predPerf = $derived(data.predPerf);
  const deals = $derived(data.deals);

  const windowDays = $derived(predPerf?.window_days ?? deals?.window_days ?? 30);

  // One normalized shape across both call sources: the live ripple calls
  // (predictions.json — ungraded "before" calls) and the recent graded calls
  // from the deal chains (deals.json). Same tier, two views, one list.
  interface Call {
    key: string;
    ticker: string;
    dir: 'long' | 'short';
    thesis: string;
    confidence: string;
    priced_in: PricedIn;
    trigger: string | null;
    ts: string | null;
    news_url: string | null;
    live: boolean;
    status: 'pending' | 'hit' | 'miss' | null;
    outcome: number | null;
  }

  function dealOutcome(p: DealPrediction): number | null {
    return p.outcomes['1d'] ?? p.outcomes['3d'] ?? p.outcomes['5d'] ?? null;
  }

  // A call is still actionable while the tape hasn't moved our way and no grade
  // has landed — the ones worth surfacing first.
  const actionable = (c: Call) =>
    c.priced_in === 'no' && c.status !== 'hit' && c.status !== 'miss';

  const calls = $derived.by((): Call[] => {
    const out: Call[] = [];
    const seen = new Set<string>();
    const push = (c: Call) => {
      if (seen.has(c.key)) return;
      seen.add(c.key);
      out.push(c);
    };

    // Live ripple calls first — they win the dedup over a later graded twin.
    for (const p of predictions?.predictions ?? []) {
      push({
        key: `${p.ticker}:${p.rationale.slice(0, 32)}`,
        ticker: p.ticker,
        dir: p.direction === 'bullish' ? 'long' : 'short',
        thesis: p.rationale,
        confidence: p.confidence,
        priced_in: p.priced_in,
        trigger: p.trigger_ticker || null,
        ts: p.created_at ?? predictions?.generated_at ?? null,
        news_url: p.news_url ?? null,
        live: true,
        status: null,
        outcome: null
      });
    }

    // Recent graded calls from the deal chains.
    for (const deal of deals?.deals ?? []) {
      for (const p of deal.predictions) {
        push({
          key: `${p.ticker}:${p.mechanism.slice(0, 32)}`,
          ticker: p.ticker,
          dir: p.direction,
          thesis: p.mechanism,
          confidence: p.confidence,
          priced_in: p.priced_in,
          trigger: deal.primary_ticker,
          ts: deal.ts,
          news_url: deal.news_url,
          live: false,
          status: p.status,
          outcome: dealOutcome(p)
        });
      }
    }

    out.sort((a, b) => {
      const aa = actionable(a) ? 0 : 1;
      const bb = actionable(b) ? 0 : 1;
      if (aa !== bb) return aa - bb;
      // Compare instants, not strings: ts sources mix UTC offsets (deal ts can be
      // -04:00/-05:00 or a +00:00 _now_iso fallback), so a lexicographic compare
      // would mis-order across offsets. Matches how /review sorts the ledger.
      return new Date(b.ts ?? 0).getTime() - new Date(a.ts ?? 0).getTime();
    });
    return out;
  });

  const actionableCount = $derived(calls.filter(actionable).length);

  const STATUS_PILL: Record<'pending' | 'hit' | 'miss', string> = {
    pending: 'pill-flat',
    hit: 'pill-up',
    miss: 'pill-down'
  };

  // ---------- Track record (prediction_performance.json) ----------
  const CONF_ORDER = ['high', 'medium', 'low'];
  const PRICED_ORDER: PricedIn[] = ['no', 'partial', 'contradicted', 'yes'];
  const PRICED_LABEL: Record<string, string> = {
    no: 'not priced in',
    partial: 'partly priced',
    contradicted: 'tape disagrees',
    yes: 'priced in'
  };

  interface ScoreRow {
    key: string;
    label: string;
    stats: AlertTypeStats;
  }

  function rowsFrom(
    group: Record<string, AlertTypeStats> | undefined,
    order: string[],
    label: (k: string) => string
  ): ScoreRow[] {
    if (!group) return [];
    const out: ScoreRow[] = [];
    const seen = new Set<string>();
    for (const k of order) {
      if (group[k]) {
        out.push({ key: k, label: label(k), stats: group[k] });
        seen.add(k);
      }
    }
    // Anything the pipeline starts logging shows up instead of vanishing.
    for (const [k, stats] of Object.entries(group)) {
      if (!seen.has(k)) out.push({ key: k, label: label(k), stats });
    }
    return out;
  }

  const byConfidence = $derived(rowsFrom(predPerf?.by_confidence, CONF_ORDER, (k) => k));
  const byPricedIn = $derived(
    rowsFrom(predPerf?.by_priced_in, PRICED_ORDER, (k) => PRICED_LABEL[k] ?? k)
  );

  // Headline: overall 1-day hit, weighted across the confidence buckets (the
  // fullest grouping). Null until something has actually been graded.
  const overall = $derived.by(() => {
    const src = predPerf?.by_confidence;
    if (!src) return null;
    let evaluated = 0;
    let hits = 0;
    for (const stats of Object.values(src)) {
      const h = stats.horizons['1d'];
      if (!h || h.evaluated == null || h.hit_rate == null) continue;
      evaluated += h.evaluated;
      hits += h.evaluated * h.hit_rate;
    }
    if (evaluated === 0) return null;
    return { hits: Math.round(hits), evaluated, pct: Math.round((hits / evaluated) * 100) };
  });

  function hitClass(rate: number | null | undefined): string {
    if (rate == null) return 'text-zinc-500';
    if (rate >= 0.6) return 'text-signal-up';
    if (rate >= 0.45) return 'text-signal-warn';
    return 'text-signal-down';
  }
  function returnClass(n: number | null | undefined): string {
    if (n == null) return 'text-zinc-500';
    if (n > 0) return 'text-signal-up';
    if (n < 0) return 'text-signal-down';
    return 'text-zinc-400';
  }
  function hitPct(rate: number | null | undefined): string {
    return rate != null ? `${(rate * 100).toFixed(0)}%` : '—';
  }
</script>

<svelte:head>
  <title>Momentum — forward calls</title>
</svelte:head>

<header class="mb-6">
  <h1 class="font-display text-2xl font-black tracking-tight">Forward calls</h1>
  <p class="text-xs text-zinc-500">
    🔮 The ripple tier reasons forward from a catalyst to who else moves — by an explicit mechanism,
    not sentiment. Reported before the tape, then graded against it. Still-actionable calls sit up
    top; the track record is underneath.
  </p>
</header>

<!-- 1 · The calls -->
<section class="mb-8" use:reveal>
  <header class="mb-3 flex flex-wrap items-center justify-between gap-2">
    <h2 class="text-sm font-semibold tracking-tight">Calls</h2>
    <div class="flex flex-wrap items-center gap-2 text-xs">
      {#if calls.length > 0}
        <span class="pill pill-pred">{calls.length} call{calls.length === 1 ? '' : 's'} · {windowDays}d</span>
      {/if}
      {#if actionableCount > 0}
        <span class="pill pill-info">{actionableCount} still actionable</span>
      {/if}
    </div>
  </header>

  {#if calls.length === 0}
    <p class="card p-4 text-xs text-zinc-500">
      No forward calls right now. A call lands here when a high-impact catalyst on a popular stock
      lets the ripple tier reason forward to another name it moves — the still-actionable ones (not
      yet priced in) surface first. The track record below holds the graded history.
    </p>
  {:else}
    <div class="card divide-y divide-ink-700/40 overflow-hidden">
      {#each calls as c (c.key)}
        {@const priced = pricedPill(c.priced_in)}
        <div class="flex flex-col gap-1.5 p-3 sm:flex-row sm:items-start sm:gap-3">
          <div class="flex shrink-0 items-center gap-2 sm:w-28">
            {#if c.dir === 'long'}
              <span class="text-signal-up">↑</span>
            {:else}
              <span class="text-signal-down">↓</span>
            {/if}
            <a href={`/t/${c.ticker}`} class="font-mono font-semibold hover:text-signal-info">{c.ticker}</a>
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-xs leading-relaxed text-zinc-300">{c.thesis}</p>
            {#if c.trigger || c.ts || c.news_url}
              <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] uppercase tracking-wider text-zinc-500">
                {#if c.trigger}
                  <span>via <a href={`/t/${c.trigger}`} class="font-mono hover:text-zinc-300">{c.trigger}</a></span>
                {/if}
                {#if c.ts}<span>· {fmtRelative(c.ts)}</span>{/if}
                {#if c.news_url}
                  <a href={c.news_url} target="_blank" rel="noopener" class="hover:text-zinc-300">· source ↗</a>
                {/if}
              </div>
            {/if}
          </div>
          <div class="flex shrink-0 flex-wrap items-center gap-1.5">
            <span class="pill {priced.cls}">{priced.text}</span>
            <span class="pill {confidencePill(c.confidence)}">{c.confidence}</span>
            {#if c.live}
              <span class="pill pill-pred">live</span>
            {:else if c.status === 'hit' || c.status === 'miss'}
              <span class="pill {STATUS_PILL[c.status]}">
                {c.status}{#if c.outcome != null}&nbsp;<span class="num">{fmtPct(c.outcome)}</span>{/if}
              </span>
            {:else}
              <span class="pill pill-flat">pending</span>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</section>

<!-- 2 · Track record -->
<section class="mb-8" use:reveal>
  <header class="mb-3 flex flex-wrap items-center justify-between gap-2">
    <h2 class="text-sm font-semibold tracking-tight">Track record</h2>
    <span class="text-[10px] uppercase tracking-wider text-zinc-500">
      {#if predPerf}
        {predPerf.total_predictions} graded calls · last {predPerf.window_days}d
      {:else}
        does the ripple tier actually pay
      {/if}
    </span>
  </header>

  {#if !predPerf || (byConfidence.length === 0 && byPricedIn.length === 0)}
    <p class="card p-4 text-xs text-zinc-500">
      No graded calls yet — stats accumulate as forward calls age past their 1/3/5-day horizons.
    </p>
  {:else}
    {#if overall}
      <div class="mb-3 flex flex-wrap items-baseline gap-2">
        <span class="font-display text-2xl font-black {hitClass(overall.pct / 100)}">{overall.pct}%</span>
        <span class="text-xs text-zinc-500">
          {overall.hits} / {overall.evaluated} graded calls hit · 1d · last {predPerf.window_days}d
        </span>
      </div>
    {/if}

    <div class="card overflow-x-auto">
      <table class="w-full min-w-[480px] text-xs">
        <thead class="bg-ink-800/40 text-[10px] uppercase tracking-wider text-zinc-500">
          <tr>
            <th class="px-3 py-2 text-left">Bucket</th>
            <th class="px-3 py-2 text-right">Calls</th>
            <th class="px-3 py-2 text-right">1d hit</th>
            <th class="px-3 py-2 text-right">1d avg</th>
          </tr>
        </thead>
        <tbody>
          {#if byConfidence.length > 0}
            <tr class="border-t border-ink-700/40">
              <td colspan="4" class="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                By confidence — does the model's conviction mean anything
              </td>
            </tr>
            {#each byConfidence as row (row.key)}
              {@const h = row.stats.horizons['1d']}
              <tr class="border-t border-ink-700/40">
                <td class="px-3 py-2"><span class="pill {confidencePill(row.key)}">{row.label}</span></td>
                <td class="num px-3 py-2 text-right text-zinc-400">{row.stats.count}</td>
                <td class="num px-3 py-2 text-right {hitClass(h?.hit_rate)}">
                  {hitPct(h?.hit_rate)}
                  {#if h?.evaluated != null}<span class="text-[10px] text-zinc-600"> ({h.evaluated})</span>{/if}
                  {#if h?.hit_rate_net != null}<div class="text-[10px] text-zinc-600">net {(h.hit_rate_net * 100).toFixed(0)}%</div>{/if}
                </td>
                <td class="num px-3 py-2 text-right {returnClass(h?.avg_return_pct)}">
                  {h?.avg_return_pct != null ? fmtPct(h.avg_return_pct) : '—'}
                  {#if h?.avg_return_net_pct != null}<div class="text-[10px] text-zinc-600">net {fmtPct(h.avg_return_net_pct)}</div>{/if}
                </td>
              </tr>
            {/each}
          {/if}

          {#if byPricedIn.length > 0}
            <tr class="border-t border-ink-700/40">
              <td colspan="4" class="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                By tape state — do the not-yet-moved calls pay
              </td>
            </tr>
            {#each byPricedIn as row (row.key)}
              {@const h = row.stats.horizons['1d']}
              <tr class="border-t border-ink-700/40">
                <td class="px-3 py-2"><span class="pill {pricedPill(row.key as PricedIn).cls}">{row.label}</span></td>
                <td class="num px-3 py-2 text-right text-zinc-400">{row.stats.count}</td>
                <td class="num px-3 py-2 text-right {hitClass(h?.hit_rate)}">
                  {hitPct(h?.hit_rate)}
                  {#if h?.evaluated != null}<span class="text-[10px] text-zinc-600"> ({h.evaluated})</span>{/if}
                  {#if h?.hit_rate_net != null}<div class="text-[10px] text-zinc-600">net {(h.hit_rate_net * 100).toFixed(0)}%</div>{/if}
                </td>
                <td class="num px-3 py-2 text-right {returnClass(h?.avg_return_pct)}">
                  {h?.avg_return_pct != null ? fmtPct(h.avg_return_pct) : '—'}
                  {#if h?.avg_return_net_pct != null}<div class="text-[10px] text-zinc-600">net {fmtPct(h.avg_return_net_pct)}</div>{/if}
                </td>
              </tr>
            {/each}
          {/if}
        </tbody>
      </table>
    </div>

    {#if predPerf.untracked_count}
      <p class="mt-2 text-[10px] uppercase tracking-wider text-signal-warn">
        {predPerf.untracked_count} pushed call{predPerf.untracked_count === 1 ? '' : 's'} currently untracked — no entry price was logged.
      </p>
    {/if}
  {/if}
</section>

<!-- 3 · Methodology -->
<footer class="space-y-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
  <p>
    A forward call is the ripple tier's second-order read: a high-impact catalyst on a popular name,
    reasoned forward to another US-listed stock it moves — supplier, customer, competitor, backup
    vendor, JV partner — with an explicit mechanism. The catalyst-grouped view lives on
    <a href="/deals" class="hover:text-zinc-300">/deals</a>.
  </p>
  <p>
    "Not priced in" means the called name hadn't moved our way yet when the call was made — the still
    actionable ones. Hit = the directional read followed through; grades come from the same ledger as
    <a href="/review" class="hover:text-zinc-300">/review</a>. Returns are gross; a net line is after
    the 0.5% round-trip slippage drag.
  </p>
  {#if predPerf?.horizon_note}
    <p>{predPerf.horizon_note}</p>
  {/if}
</footer>
