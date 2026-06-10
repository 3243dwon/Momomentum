<script lang="ts">
  import { goto } from '$app/navigation';
  import { fmtPct, pctClass } from '$lib/format';

  let query = $state('');
  let active = $state(false);
  let highlighted = $state(-1);

  // Lazily fetched ticker list for suggestions — scan rows carry pct_1d so the
  // dropdown doubles as a mini quote. Free-text still navigates (the ticker
  // hub renders gracefully for non-scan names).
  let tickers: { ticker: string; pct_1d: number | null }[] = $state([]);
  let fetched = false;
  async function ensureTickers() {
    if (fetched) return;
    fetched = true;
    try {
      const r = await fetch('/data/scan.json');
      if (!r.ok) return;
      const j = await r.json();
      tickers = (j.rows ?? []).map((row: { ticker: string; pct_1d: number | null }) => ({
        ticker: row.ticker,
        pct_1d: row.pct_1d
      }));
    } catch {
      // suggestions are an enhancement, not a requirement
    }
  }

  const suggestions = $derived.by(() => {
    const q = query.trim().toUpperCase();
    if (!q) return [];
    const starts = tickers.filter((t) => t.ticker.startsWith(q));
    const contains = tickers.filter((t) => !t.ticker.startsWith(q) && t.ticker.includes(q));
    return [...starts, ...contains].slice(0, 8);
  });

  function go(ticker: string) {
    goto(`/t/${ticker.toUpperCase()}`);
    query = '';
    active = false;
    highlighted = -1;
  }

  function submit(e: Event) {
    e.preventDefault();
    if (highlighted >= 0 && suggestions[highlighted]) return go(suggestions[highlighted].ticker);
    const t = query.trim().toUpperCase();
    if (!t) return;
    go(t);
  }

  function onKeydown(e: KeyboardEvent) {
    if (!suggestions.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      highlighted = (highlighted + 1) % suggestions.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      highlighted = highlighted <= 0 ? suggestions.length - 1 : highlighted - 1;
    } else if (e.key === 'Escape') {
      active = false;
      highlighted = -1;
    }
  }
</script>

<form onsubmit={submit} class="relative">
  <input
    bind:value={query}
    onfocus={() => {
      active = true;
      void ensureTickers();
    }}
    onblur={() => setTimeout(() => (active = false), 150)}
    onkeydown={onKeydown}
    oninput={() => (highlighted = -1)}
    type="search"
    placeholder="Ticker..."
    autocomplete="off"
    class="num w-20 rounded bg-ink-800 px-2 py-1 text-xs uppercase placeholder:text-zinc-500 placeholder:normal-case focus:w-32 focus:outline-none focus:ring-1 focus:ring-signal-info focus:placeholder:text-zinc-600"
  />
  {#if active && suggestions.length > 0}
    <ul class="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-md border border-ink-700 bg-ink-900 shadow-lg">
      {#each suggestions as s, i (s.ticker)}
        <li>
          <button
            type="button"
            onmousedown={(e) => {
              e.preventDefault();
              go(s.ticker);
            }}
            class="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-xs transition-colors {i === highlighted ? 'bg-ink-700' : 'hover:bg-ink-800'}"
          >
            <span class="num font-semibold">{s.ticker}</span>
            <span class="num {pctClass(s.pct_1d)}">{fmtPct(s.pct_1d)}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</form>
