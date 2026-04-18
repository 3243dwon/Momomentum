<script lang="ts">
  import { browser } from '$app/environment';

  export type Filters = {
    size: 'any' | 'large' | 'midsmall';
    move: 'any' | 'p3' | 'p5';
    volume: 'any' | 'unusual';
    news: 'any' | 'with';
    vwap: 'any' | 'above';
  };

  const DEFAULTS: Filters = {
    size: 'any',
    move: 'any',
    volume: 'any',
    news: 'any',
    vwap: 'any'
  };

  // Named scan presets based on professional momentum setups. Each applies
  // a combo of filters; clicking again deselects back to defaults.
  const PRESETS: { id: string; label: string; desc: string; apply: Filters }[] = [
    {
      id: 'all',
      label: 'All',
      desc: 'no filters — show everything',
      apply: { ...DEFAULTS }
    },
    {
      id: 'gap-go',
      label: 'Gap & Go',
      desc: 'catalyst-driven open — big move + heavy volume + above VWAP',
      apply: { ...DEFAULTS, move: 'p3', volume: 'unusual', vwap: 'above' }
    },
    {
      id: 'catalyst',
      label: 'Catalyst Movers',
      desc: 'news-explained movers only — the actionable set',
      apply: { ...DEFAULTS, move: 'p3', news: 'with' }
    },
    {
      id: 'high-conviction',
      label: 'High Conviction',
      desc: 'big move + news + above VWAP — pro institutional setup',
      apply: { ...DEFAULTS, move: 'p3', news: 'with', vwap: 'above' }
    },
    {
      id: 'midsmall-play',
      label: 'Mid/Small Plays',
      desc: 'outsized moves in mid+small cap where risk-reward lives',
      apply: { ...DEFAULTS, size: 'midsmall', move: 'p5' }
    },
    {
      id: 'momentum-burst',
      label: 'Momentum Burst',
      desc: 'explosive 5%+ moves on 2x volume — regardless of news',
      apply: { ...DEFAULTS, move: 'p5', volume: 'unusual' }
    }
  ];

  const STORAGE_KEY = 'momentum:filters';

  function load(): Filters {
    if (!browser) return DEFAULTS;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return DEFAULTS;
      return { ...DEFAULTS, ...JSON.parse(raw) };
    } catch {
      return DEFAULTS;
    }
  }

  let { filters = $bindable() }: { filters: Filters } = $props();

  if (browser) filters = load();

  function persist() {
    if (!browser) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
    } catch {}
  }

  function reset() {
    filters = { ...DEFAULTS };
    persist();
  }

  const isActive = $derived(
    filters.size !== 'any' ||
      filters.move !== 'any' ||
      filters.volume !== 'any' ||
      filters.news !== 'any' ||
      filters.vwap !== 'any'
  );

  type Group<K extends keyof Filters> = {
    key: K;
    label: string;
    options: { value: Filters[K]; label: string }[];
  };

  const groups: [
    Group<'size'>,
    Group<'move'>,
    Group<'volume'>,
    Group<'news'>,
    Group<'vwap'>
  ] = [
    {
      key: 'size',
      label: 'Size',
      options: [
        { value: 'any', label: 'Any' },
        { value: 'large', label: 'Large+' },
        { value: 'midsmall', label: 'Mid/small' }
      ]
    },
    {
      key: 'move',
      label: 'Move',
      options: [
        { value: 'any', label: 'Any' },
        { value: 'p3', label: '≥3%' },
        { value: 'p5', label: '≥5%' }
      ]
    },
    {
      key: 'volume',
      label: 'Volume',
      options: [
        { value: 'any', label: 'Any' },
        { value: 'unusual', label: '≥2× avg' }
      ]
    },
    {
      key: 'news',
      label: 'News',
      options: [
        { value: 'any', label: 'Any' },
        { value: 'with', label: 'With news' }
      ]
    },
    {
      key: 'vwap',
      label: 'VWAP',
      options: [
        { value: 'any', label: 'Any' },
        { value: 'above', label: 'Above' }
      ]
    }
  ];

  function set<K extends keyof Filters>(key: K, value: Filters[K]) {
    filters = { ...filters, [key]: value };
    persist();
  }

  function applyPreset(preset: Filters) {
    filters = { ...preset };
    persist();
  }

  function matches(preset: Filters): boolean {
    return (
      filters.size === preset.size &&
      filters.move === preset.move &&
      filters.volume === preset.volume &&
      filters.news === preset.news &&
      filters.vwap === preset.vwap
    );
  }
</script>

<section class="card mb-2 flex flex-wrap items-center gap-1.5 p-2 text-[10px] uppercase tracking-wider">
  <span class="px-1 text-zinc-500">Scan preset</span>
  {#each PRESETS as p}
    <button
      type="button"
      onclick={() => applyPreset(p.apply)}
      title={p.desc}
      class="rounded px-2 py-1 transition-colors {matches(p.apply)
        ? 'bg-signal-warn/15 text-signal-warn'
        : 'text-zinc-400 hover:bg-ink-800 hover:text-zinc-200'}"
    >
      {p.label}
    </button>
  {/each}
</section>

<details class="mb-2 text-xs">
  <summary class="cursor-pointer px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300">
    What do these presets mean?
  </summary>
  <div class="card mt-1 space-y-2 p-3 leading-relaxed">
    <p>
      <span class="font-medium text-zinc-200">All</span>
      <span class="text-zinc-500">— no filters. Widest funnel, most noise. Good for browsing.</span>
    </p>
    <p>
      <span class="font-medium text-zinc-200">Gap &amp; Go</span>
      <span class="text-zinc-500">— ≥3% move + ≥2× volume + above VWAP. Classic open-session play: stock gapped on news, buyers are still holding it. Use pre-market / first hour of trading.</span>
    </p>
    <p>
      <span class="font-medium text-zinc-200">Catalyst Movers</span>
      <span class="text-zinc-500">— ≥3% move + has news. Best default. Filters to movers with a published "why" you can skim in seconds. You won't trade blind momentum.</span>
    </p>
    <p>
      <span class="font-medium text-zinc-200">High Conviction</span>
      <span class="text-zinc-500">— Catalyst Movers + above VWAP. Tightest set: news-driven AND institutional buyers still in control. When this has names, they're the setups worth acting on.</span>
    </p>
    <p>
      <span class="font-medium text-zinc-200">Mid/Small Plays</span>
      <span class="text-zinc-500">— mid+small cap with ≥5% move. Excludes mega-caps. Small caps make bigger % moves — bigger potential upside and downside.</span>
    </p>
    <p>
      <span class="font-medium text-zinc-200">Momentum Burst</span>
      <span class="text-zinc-500">— ≥5% move on ≥2× volume. News or not. Something's happening, figure out why later. Riskier without catalyst context.</span>
    </p>
    <p class="border-t border-ink-700 pt-2 text-zinc-500">
      <span class="font-medium text-zinc-400">Heads up:</span>
      VWAP is an intraday metric (5-min bars during market hours 9:30–16:00 ET). Off-hours, presets using &ldquo;above VWAP&rdquo; (Gap &amp; Go, High Conviction) will usually be empty. Default to Catalyst Movers after hours.
    </p>
  </div>
</details>

<section class="card mb-4 flex flex-wrap items-center gap-2 p-2 text-[10px] uppercase tracking-wider">
  {#each groups as g}
    <div class="flex items-center gap-1">
      <span class="px-1 text-zinc-500">{g.label}</span>
      <div class="flex gap-1">
        {#each g.options as o}
          <button
            type="button"
            onclick={() => set(g.key, o.value)}
            class="rounded px-2 py-1 transition-colors {filters[g.key] === o.value
              ? 'bg-signal-info/15 text-signal-info'
              : 'text-zinc-400 hover:bg-ink-800'}"
          >
            {o.label}
          </button>
        {/each}
      </div>
    </div>
  {/each}
  {#if isActive}
    <button
      type="button"
      onclick={reset}
      class="ml-auto rounded px-2 py-1 text-zinc-500 hover:bg-ink-800 hover:text-zinc-200"
    >
      Reset
    </button>
  {/if}
</section>
