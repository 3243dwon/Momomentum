<script lang="ts">
  import { goto } from '$app/navigation';

  let query = $state('');
  let active = $state(false);

  function submit(e: Event) {
    e.preventDefault();
    const t = query.trim().toUpperCase();
    if (!t) return;
    goto(`/t/${t}`);
    query = '';
    active = false;
  }
</script>

<form onsubmit={submit} class="relative">
  <input
    bind:value={query}
    onfocus={() => (active = true)}
    onblur={() => setTimeout(() => (active = false), 150)}
    type="search"
    placeholder="Go to ticker..."
    class="num w-24 rounded bg-ink-800 px-2 py-1 text-xs uppercase placeholder:text-zinc-500 placeholder:normal-case focus:w-32 focus:outline-none focus:ring-1 focus:ring-signal-info focus:placeholder:text-zinc-600"
  />
</form>
