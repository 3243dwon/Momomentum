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
</script>

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
