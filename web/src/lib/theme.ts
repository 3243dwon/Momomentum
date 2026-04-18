// Theme store. Mirrors the inline anti-FOUC script in app.html.
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'momentum:theme';

function readInitial(): Theme {
  if (!browser) return 'dark';
  const attr = document.documentElement.getAttribute('data-theme');
  if (attr === 'light' || attr === 'dark') return attr;
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function apply(t: Theme) {
  if (!browser) return;
  document.documentElement.setAttribute('data-theme', t);
  try {
    localStorage.setItem(STORAGE_KEY, t);
  } catch {
    /* private browsing, ignore */
  }
}

function createTheme() {
  const { subscribe, set, update } = writable<Theme>(readInitial());

  return {
    subscribe,
    set: (t: Theme) => {
      apply(t);
      set(t);
    },
    toggle: () =>
      update((t) => {
        const next: Theme = t === 'dark' ? 'light' : 'dark';
        apply(next);
        return next;
      })
  };
}

export const theme = createTheme();
