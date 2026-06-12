<script lang="ts">
  import { fmtPct, fmtRelative, pctClass, confidencePill } from '$lib/format';
  import type { Deal, DealPrediction } from '$lib/types';

  let { data } = $props();
  const deals = $derived(data.deals?.deals ?? []);
  const windowDays = $derived(data.deals?.window_days ?? 30);

  // Still-actionable calls are the ones the ripple flagged as not yet priced in.
  const liveCount = $derived(
    deals.reduce(
      (n: number, d: Deal) => n + d.predictions.filter((p) => p.priced_in === 'no').length,
      0
    )
  );

  const STATUS_PILL: Record<DealPrediction['status'], string> = {
    pending: 'pill-flat',
    hit: 'pill-up',
    miss: 'pill-down'
  };

  // priced_in is the headline signal of the section: a call that hasn't been
  // priced in yet is the one you can still act on.
  function pricedPill(p: DealPrediction): { text: string; cls: string } {
    if (p.priced_in === 'no') return { text: 'not priced in', cls: 'pill-info' };
    if (p.priced_in === 'partial') return { text: 'partly priced', cls: 'pill-warn' };
    return { text: 'priced in', cls: 'pill-flat' };
  }

  function firstOutcome(p: DealPrediction): number | null {
    return p.outcomes['1d'] ?? p.outcomes['3d'] ?? p.outcomes['5d'] ?? null;
  }
</script>

<svelte:head>
  <title>Momentum — deal flow</title>
</svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">Deal flow</h1>
  <p class="text-xs text-zinc-500">
    The deals and catalysts moving popular names — and the second-order calls each one sets up.
    Reported forward: who else moves, by what mechanism, and whether it's still actionable.
  </p>
</header>

{#if deals.length === 0}
  <p class="card p-4 text-xs text-zinc-500">
    No deals in the last {windowDays} days. A deal lands here when a high-impact catalyst on a
    popular stock lets the ripple tier reason forward to who else it moves.
  </p>
{:else}
  <div class="mb-4 flex flex-wrap items-center gap-2 text-xs">
    <span class="pill pill-info">{deals.length} deals · {windowDays}d</span>
    {#if liveCount > 0}
      <span class="pill pill-up">{liveCount} calls still not priced in</span>
    {/if}
    <span class="ml-auto text-[10px] uppercase tracking-wider text-zinc-500">
      deal → who else moves → graded
    </span>
  </div>

  <div class="space-y-4">
    {#each deals as deal (deal.id)}
      {@const live = deal.predictions.filter((p) => p.priced_in === 'no').length}
      <article class="card overflow-hidden">
        <!-- Deal header: the principals + what happened -->
        <header class="border-b border-ink-700/60 bg-ink-800/30 p-4">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <span class="text-[10px] uppercase tracking-wider text-zinc-500">deal</span>
            <a href={`/t/${deal.primary_ticker}`} class="font-mono text-lg font-semibold hover:text-signal-info">
              {deal.primary_ticker}
            </a>
            {#if deal.counterparty}
              <span class="text-zinc-600">×</span>
              <a href={`/t/${deal.counterparty}`} class="font-mono text-lg font-semibold hover:text-signal-info">
                {deal.counterparty}
              </a>
            {/if}
            <span class="ml-auto text-[10px] uppercase tracking-wider text-zinc-500">
              {fmtRelative(deal.ts)}
            </span>
          </div>
          <p class="text-sm leading-relaxed text-zinc-300">{deal.headline}</p>
          {#if deal.drivers.length > 0}
            <ul class="mt-2 space-y-0.5">
              {#each deal.drivers.slice(0, 3) as driver}
                <li class="flex gap-1.5 text-xs text-zinc-500">
                  <span class="text-zinc-600">·</span>{driver}
                </li>
              {/each}
            </ul>
          {/if}
          <div class="mt-3 flex flex-wrap items-center gap-3 text-[10px] uppercase tracking-wider text-zinc-500">
            <span>{deal.stats.calls} ripple calls</span>
            {#if deal.stats.graded > 0}
              <span class="text-signal-up">{deal.stats.hit}/{deal.stats.graded} hit</span>
            {:else}
              <span>awaiting grades</span>
            {/if}
            {#if live > 0}
              <span class="text-signal-info">{live} still actionable</span>
            {/if}
            {#if deal.news_url}
              <a href={deal.news_url} target="_blank" rel="noopener" class="ml-auto hover:text-zinc-300">
                source ↗
              </a>
            {/if}
          </div>
        </header>

        <!-- The chain: who else this deal moves -->
        <div class="divide-y divide-ink-700/40">
          {#each deal.predictions as p (p.ticker + p.mechanism.slice(0, 20))}
            {@const out = firstOutcome(p)}
            {@const priced = pricedPill(p)}
            <div class="flex flex-col gap-1.5 p-3 sm:flex-row sm:items-start sm:gap-3">
              <div class="flex shrink-0 items-center gap-2 sm:w-28">
                {#if p.direction === 'long'}
                  <span class="text-signal-up">↑</span>
                {:else}
                  <span class="text-signal-down">↓</span>
                {/if}
                <a href={`/t/${p.ticker}`} class="font-mono font-semibold hover:text-signal-info">{p.ticker}</a>
              </div>
              <p class="min-w-0 flex-1 text-xs leading-relaxed text-zinc-400">{p.mechanism}</p>
              <div class="flex shrink-0 flex-wrap items-center gap-1.5">
                <span class="pill {priced.cls}">{priced.text}</span>
                <span class="pill {confidencePill(p.confidence)}">{p.confidence}</span>
                {#if p.status !== 'pending'}
                  <span class="pill {STATUS_PILL[p.status]}">
                    {p.status}{#if out != null}&nbsp;<span class="num">{fmtPct(out)}</span>{/if}
                  </span>
                {:else}
                  <span class="pill pill-flat">pending</span>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </article>
    {/each}
  </div>

  <footer class="mt-6 space-y-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
    <p>
      A deal is a high-impact catalyst on a popular stock. The ripple tier reasons forward from it
      to other US-listed names — suppliers, customers, competitors, backup vendors, JV partners —
      with an explicit mechanism, not sentiment.
    </p>
    <p>
      "Not priced in" means the predicted name hadn't moved yet when the call was made — the still
      actionable ones. Grades come from the same ledger as <a href="/review" class="hover:text-zinc-300">/review</a>:
      a call is a hit if its directional read followed through.
    </p>
  </footer>
{/if}
