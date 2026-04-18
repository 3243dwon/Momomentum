<script lang="ts">
  import { theme } from '$lib/theme';
</script>

<button
  type="button"
  onclick={theme.toggle}
  aria-label="Toggle theme"
  title={$theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
  class="grid h-7 w-7 place-items-center rounded text-zinc-400 transition-colors hover:bg-ink-800 hover:text-zinc-100"
>
  {#if $theme === 'dark'}
    <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  {:else}
    <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  {/if}
</button>
