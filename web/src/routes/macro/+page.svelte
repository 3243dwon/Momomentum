<script lang="ts">
  import { confidencePill } from '$lib/format';

  let { data } = $props();
  const macroEvents = data.news?.macro_events ?? [];
</script>

<svelte:head>
  <title>Macro — Momentum</title>
</svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">Macro events</h1>
  <p class="text-xs text-zinc-500">
    Opus-tier analysis: who benefits, who loses. Each event groups headlines covering the same story.
  </p>
</header>

{#if macroEvents.length === 0}
  <div class="card p-8 text-center text-zinc-400">
    <p class="text-sm">No macro events analyzed in the latest scan.</p>
    <p class="mt-2 text-xs text-zinc-500">
      Macro RSS feeds are checked every 30min; events get LLM analysis when classified high or medium impact.
    </p>
  </div>
{:else}
  <div class="space-y-4">
    {#each macroEvents as event}
      <article class="card p-4">
        <h2 class="text-base font-semibold tracking-tight">{event.event_summary}</h2>

        {#if event.primary_drivers?.length}
          <div class="mt-2 flex flex-wrap gap-1">
            {#each event.primary_drivers as d}
              <span class="pill-flat">{d}</span>
            {/each}
          </div>
        {/if}

        {#if event.headlines?.length}
          <ul class="mt-3 space-y-1 text-xs text-zinc-500">
            {#each event.headlines as h}
              <li>· {h}</li>
            {/each}
          </ul>
        {/if}

        <div class="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <h3 class="mb-2 text-[10px] uppercase tracking-wider text-signal-up">Beneficiaries</h3>
            {#if event.beneficiaries?.length}
              <ul class="space-y-2">
                {#each event.beneficiaries as b}
                  <li class="rounded border border-signal-up/20 bg-signal-up/5 p-2">
                    <div class="mb-1 flex items-center gap-2">
                      <a href={`/t/${b.ticker}`} class="font-semibold text-signal-up hover:underline">{b.ticker}</a>
                      <span class="pill {confidencePill(b.confidence)}">{b.confidence}</span>
                      <span class="pill-flat">{b.horizon}</span>
                    </div>
                    <p class="text-xs text-zinc-300">{b.rationale}</p>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="text-xs text-zinc-500">None identified.</p>
            {/if}
          </div>

          <div>
            <h3 class="mb-2 text-[10px] uppercase tracking-wider text-signal-down">Losers</h3>
            {#if event.losers?.length}
              <ul class="space-y-2">
                {#each event.losers as l}
                  <li class="rounded border border-signal-down/20 bg-signal-down/5 p-2">
                    <div class="mb-1 flex items-center gap-2">
                      <a href={`/t/${l.ticker}`} class="font-semibold text-signal-down hover:underline">{l.ticker}</a>
                      <span class="pill {confidencePill(l.confidence)}">{l.confidence}</span>
                      <span class="pill-flat">{l.horizon}</span>
                    </div>
                    <p class="text-xs text-zinc-300">{l.rationale}</p>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="text-xs text-zinc-500">None identified.</p>
            {/if}
          </div>
        </div>
      </article>
    {/each}
  </div>
{/if}
