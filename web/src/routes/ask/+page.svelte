<script lang="ts">
  import { browser } from '$app/environment';

  let { data } = $props();

  const TOKEN_KEY = 'momentum:ask-token';
  const MAX_CHARS = 400;

  const EXAMPLES = [
    'Is $NVDA chaseable here or extended?',
    'What did Serenity say about COHR?',
    'How are the desk takes performing?',
    '什么板块今天在动？'
  ];

  type AskItem = {
    id: number;
    question: string;
    status: 'loading' | 'done' | 'error';
    answer?: string;
    model?: string;
    ageMin?: number;
    tickers?: string[];
    error?: string;
  };

  // --- Token: single-user bearer, persisted in this browser only. A 401
  // clears it and reopens setup — the stored value is the only auth state.
  const stored = browser ? localStorage.getItem(TOKEN_KEY) : null;
  let token = $state(stored ?? '');
  let tokenInput = $state('');
  let setupOpen = $state(!stored);
  let tokenNote = $state('');

  function saveToken(e: SubmitEvent) {
    e.preventDefault();
    const t = tokenInput.trim();
    if (!t) return;
    token = t;
    if (browser) localStorage.setItem(TOKEN_KEY, t);
    tokenInput = '';
    setupOpen = false;
    tokenNote = '';
  }

  // --- Conversation: session-only, newest first. Items settle in place via
  // map-replace so the shimmer card becomes the answer (or an error line).
  // svelte-ignore state_referenced_locally — ?q= prefill is intentionally read once
  let question = $state(data.q);
  let busy = $state(false);
  let history = $state<AskItem[]>([]);
  let nextId = 0;

  const rows = $derived(Math.min(3, Math.max(1, question.split('\n').length)));

  function patch(id: number, p: Partial<AskItem>) {
    history = history.map((h) => (h.id === id ? { ...h, ...p } : h));
  }

  async function send() {
    const q = question.trim();
    if (!q || busy) return;
    if (!token) {
      setupOpen = true;
      tokenNote = 'paste your access token first';
      return;
    }
    const id = nextId++;
    history = [{ id, question: q, status: 'loading' }, ...history];
    question = '';
    busy = true;
    try {
      const r = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-ask-token': token },
        body: JSON.stringify({ question: q })
      });
      let body: {
        answer?: string;
        model?: string;
        data_age_minutes?: number;
        tickers?: string[];
        error?: string;
      } | null = null;
      try {
        body = await r.json();
      } catch {
        // non-JSON body (proxy error page) — fall through to the generic line
      }
      if (r.ok && body?.answer) {
        patch(id, {
          status: 'done',
          answer: body.answer,
          model: body.model,
          ageMin: body.data_age_minutes,
          tickers: body.tickers ?? []
        });
      } else if (r.status === 401) {
        token = '';
        if (browser) localStorage.removeItem(TOKEN_KEY);
        setupOpen = true;
        tokenNote = 'token rejected by the server — paste it again';
        question = q; // restore so the question survives the re-auth
        patch(id, {
          status: 'error',
          error: 'Unauthorized — the stored token was cleared. Set it again above and resend.'
        });
      } else if (r.status === 503) {
        patch(id, {
          status: 'error',
          error: "Ask isn't configured on this deployment yet — add ANTHROPIC_API_KEY and ASK_TOKEN in Vercel."
        });
      } else {
        patch(id, { status: 'error', error: body?.error ?? `request failed (${r.status})` });
      }
    } catch {
      patch(id, { status: 'error', error: 'network error — the request never reached the server' });
    } finally {
      busy = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    // Enter sends, Shift+Enter breaks a line; ignore mid-IME Enter so Chinese
    // input doesn't fire the question while composing.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      void send();
    }
  }

  function ageLabel(min?: number): string {
    if (min == null || !Number.isFinite(min)) return 'data age unknown';
    if (min < 1) return 'data was <1m old';
    if (min < 60) return `data was ${min}m old`;
    return `data was ${Math.floor(min / 60)}h ${min % 60}m old`;
  }
</script>

<svelte:head>
  <title>Momentum — ask</title>
</svelte:head>

<header class="mb-6">
  <h1 class="text-lg font-semibold tracking-tight">Ask the tape</h1>
  <p class="text-xs text-zinc-500">
    Answers come from the latest committed scan/news/ledger JSON — batch data, not live, not advice.
  </p>
</header>

{#if setupOpen}
  <section class="card mb-4 p-3">
    <label for="ask-token" class="text-[10px] uppercase tracking-wider text-zinc-500">Access token</label>
    <form class="mt-1.5 flex items-center gap-2" onsubmit={saveToken}>
      <input
        id="ask-token"
        type="password"
        bind:value={tokenInput}
        placeholder="ask token"
        autocomplete="off"
        class="min-w-0 flex-1 rounded border border-ink-700 bg-ink-950 px-2.5 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-signal-info/60 focus:outline-none"
      />
      <button
        type="submit"
        disabled={!tokenInput.trim()}
        class="rounded bg-signal-info/10 px-3 py-1.5 text-xs font-medium text-signal-info transition-colors hover:bg-signal-info/20 disabled:cursor-not-allowed disabled:opacity-40"
      >
        Save
      </button>
      {#if token}
        <button
          type="button"
          onclick={() => {
            setupOpen = false;
            tokenInput = '';
            tokenNote = '';
          }}
          class="text-[11px] text-zinc-500 hover:text-zinc-300"
        >
          keep current
        </button>
      {/if}
    </form>
    {#if tokenNote}
      <p class="mt-1.5 text-[11px] text-signal-down">{tokenNote}</p>
    {/if}
    <p class="mt-1.5 text-[11px] text-zinc-500">set ASK_TOKEN in Vercel env, paste it here once — kept only in this browser</p>
  </section>
{/if}

<section class="mb-8">
  <form
    class="card p-3"
    onsubmit={(e) => {
      e.preventDefault();
      void send();
    }}
  >
    <textarea
      bind:value={question}
      onkeydown={onKeydown}
      {rows}
      maxlength={MAX_CHARS}
      disabled={busy}
      aria-label="Ask a question about the scan"
      placeholder="Ask about a ticker, the desk takes, Serenity, the ledger…"
      class="w-full resize-none bg-transparent text-sm leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:outline-none disabled:opacity-50"
    ></textarea>
    <div class="mt-2 flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500">
        <span class="hidden sm:inline">enter to send · shift+enter for newline</span>
        {#if token && !setupOpen}
          <button
            type="button"
            onclick={() => {
              setupOpen = true;
              tokenNote = '';
            }}
            class="underline-offset-2 hover:text-zinc-300 hover:underline"
          >
            change token
          </button>
        {/if}
      </div>
      <div class="flex shrink-0 items-center gap-2">
        {#if question.length > 300}
          <span class="num text-[10px] {question.length >= MAX_CHARS ? 'text-signal-down' : 'text-signal-warn'}">
            {question.length}/{MAX_CHARS}
          </span>
        {/if}
        <button
          type="submit"
          disabled={busy || !question.trim()}
          class="rounded bg-signal-info/10 px-3 py-1.5 text-xs font-medium text-signal-info transition-colors hover:bg-signal-info/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? 'Asking…' : 'Send'}
        </button>
      </div>
    </div>
  </form>

  {#if history.length === 0}
    <div class="mt-3 flex flex-wrap gap-1.5">
      {#each EXAMPLES as ex (ex)}
        <button
          type="button"
          onclick={() => (question = ex)}
          class="rounded border border-ink-700 bg-ink-900 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-ink-600 hover:text-zinc-200"
        >
          {ex}
        </button>
      {/each}
    </div>
  {/if}
</section>

{#if history.length > 0}
  <section class="mb-8 space-y-5">
    {#each history as item (item.id)}
      <article>
        <p class="mb-1.5 whitespace-pre-wrap text-xs text-zinc-500">{item.question}</p>
        {#if item.status === 'loading'}
          <div class="card animate-pulse space-y-2 p-4">
            <div class="h-3 w-3/4 rounded bg-ink-700"></div>
            <div class="h-3 w-full rounded bg-ink-700"></div>
            <div class="h-3 w-1/2 rounded bg-ink-700"></div>
          </div>
        {:else if item.status === 'error'}
          <p class="text-xs leading-relaxed text-signal-down">{item.error}</p>
        {:else}
          <div class="card p-4">
            <p class="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">{item.answer}</p>
          </div>
          <div class="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] uppercase tracking-wider text-zinc-500">
            <span>{ageLabel(item.ageMin)}</span>
            <span>·</span>
            <span>{item.model}</span>
            {#if item.tickers?.length}
              <span>·</span>
              {#each item.tickers as t (t)}
                <a href={`/t/${t}`} class="pill-info num transition-colors hover:bg-signal-info/20">{t}</a>
              {/each}
            {/if}
          </div>
        {/if}
      </article>
    {/each}
  </section>
{/if}
