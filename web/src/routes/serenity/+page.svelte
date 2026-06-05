<script lang="ts">
  import { fmtPct, pctClass, fmtRelative } from '$lib/format';
  import type { SerenityTweet, ScanRow } from '$lib/types';

  let { data } = $props();
  const feed = data.serenity;
  const tweets: SerenityTweet[] = feed?.tweets ?? [];

  // Live-scan cross-reference, computed client-side from scan.json.
  const HOT = 3.0;
  const rowByTicker = new Map<string, ScanRow>((data.scan?.rows ?? []).map((r) => [r.ticker, r]));

  function live(ticker: string): { pct: number | null; moving: boolean } | undefined {
    const r = rowByTicker.get(ticker);
    if (!r) return undefined;
    return { pct: r.pct_1d, moving: r.pct_1d != null && Math.abs(r.pct_1d) >= HOT };
  }

  // Tickers Serenity named that are moving in the current scan.
  const matched = Array.from(new Set(tweets.flatMap((t) => t.tickers).filter((tk) => live(tk)?.moving)));

  // US convention here (unlike the CN-styled lengjing page): bull = green = up.
  const STANCE: Record<string, { label: string; cls: string }> = {
    bull: { label: 'BULL', cls: 'text-signal-up' },
    bear: { label: 'BEAR', cls: 'text-signal-down' },
    neutral: { label: 'NEUTRAL', cls: 'text-zinc-400' }
  };
</script>

<svelte:head>
  <title>Serenity — Momentum</title>
</svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">🧠 Serenity</h1>
  <p class="text-xs text-zinc-500">
    <a
      href="https://x.com/aleabitoreddit"
      target="_blank"
      rel="noopener noreferrer"
      class="hover:underline">@aleabitoreddit</a
    >
    on AI-infrastructure & semiconductors — polled 24/7, tickers cross-referenced against the live scan.
  </p>
</header>

{#if matched.length}
  <div class="card mb-4 p-3">
    <span class="text-[10px] uppercase tracking-wider text-signal-info">Live matches this scan</span>
    <div class="mt-1.5 flex flex-wrap gap-1.5">
      {#each matched as t}
        <a href={`/t/${t}`} class="pill pill-warn hover:underline">{t}</a>
      {/each}
    </div>
  </div>
{/if}

{#if tweets.length === 0}
  <div class="card p-8 text-center text-zinc-400">
    <p class="text-sm">No Serenity tweets ingested yet.</p>
    <p class="mt-2 text-xs text-zinc-500">
      The 24/7 poller writes them here once <code>X_BEARER_TOKEN</code> is configured.
    </p>
  </div>
{:else}
  <div class="space-y-4">
    {#each tweets as t (t.id)}
      {@const stance = STANCE[t.stance] ?? STANCE.neutral}
      <article class="card p-4">
        <div class="mb-2 flex items-center justify-between gap-2">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-[10px] font-semibold uppercase tracking-wider {stance.cls}">{stance.label}</span>
            {#each t.tickers as tk}
              {@const lv = live(tk)}
              <a
                href={`/t/${tk}`}
                class="font-mono text-xs hover:underline {lv?.moving ? pctClass(lv.pct) : 'text-zinc-300'}"
              >
                ${tk}{#if lv?.moving}<span class="ml-1">{fmtPct(lv.pct)}</span>{/if}
              </a>
            {/each}
          </div>
          <span class="whitespace-nowrap text-xs text-zinc-500">{fmtRelative(t.createdAt)}</span>
        </div>

        <p class="whitespace-pre-line text-sm leading-relaxed text-zinc-200">{t.text}</p>

        {#if t.summaryEn}
          <p class="mt-2 text-xs italic text-zinc-400">{t.summaryEn}</p>
        {/if}

        <div class="mt-3 flex items-center justify-between gap-2">
          {#if t.metrics}
            <div class="text-xs text-zinc-500">
              ♥ {t.metrics.likes.toLocaleString()} · ↻ {t.metrics.reposts.toLocaleString()} · 💬 {t.metrics.replies.toLocaleString()}
            </div>
          {:else}
            <span></span>
          {/if}
          <a
            href={t.url}
            target="_blank"
            rel="noopener noreferrer"
            class="whitespace-nowrap text-xs font-medium text-signal-info hover:underline">View on X ↗</a
          >
        </div>
      </article>
    {/each}
  </div>
{/if}
