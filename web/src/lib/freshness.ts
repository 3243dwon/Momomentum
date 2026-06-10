// Staleness signaling + the auto-refresh loop the dashboard never had.
// `now` ticks every 30s so relative-time labels don't freeze; startScanWatch
// polls scan.json's generated_at on tab-resume and on an interval and
// invalidates all loads when a new scan lands.
import { readable, writable } from 'svelte/store';
import { invalidateAll } from '$app/navigation';

export const now = readable(Date.now(), (set) => {
  const id = setInterval(() => set(Date.now()), 30_000);
  return () => clearInterval(id);
});

/** Market regime from the latest scan — rides along on the scan-watch fetch
 * so the layout can tint without its own data load. */
export const regimeLabel = writable<'risk_on' | 'risk_off' | 'mixed' | null>(null);

export type StaleLevel = 'fresh' | 'aging' | 'stale';

// Thresholds follow the real pipeline cadence: scans land every ~2-3h during
// the week (GitHub drops most hourly crons), so <90min is as fresh as it gets.
export function staleness(iso: string | null | undefined, nowMs: number): { level: StaleLevel; ageMin: number } {
  if (!iso) return { level: 'stale', ageMin: Infinity };
  const ageMin = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 60_000));
  if (ageMin < 90) return { level: 'fresh', ageMin };
  if (ageMin < 180) return { level: 'aging', ageMin };
  return { level: 'stale', ageMin };
}

export const STALE_CLASS: Record<StaleLevel, string> = {
  fresh: 'text-signal-up',
  aging: 'text-signal-warn',
  stale: 'text-signal-down'
};

export function fmtAge(ageMin: number): string {
  if (!Number.isFinite(ageMin)) return 'no data';
  if (ageMin < 1) return 'just now';
  if (ageMin < 60) return `${ageMin}m ago`;
  const h = Math.floor(ageMin / 60);
  if (h < 24) return `${h}h ${ageMin % 60}m ago`;
  return `${Math.round(h / 24)}d ago`;
}

let watching = false;
let lastGeneratedAt: string | null = null;

/** Call once from the root layout (browser only). Refetches scan.json's
 * generated_at on visibilitychange + every 5 minutes; when it changes,
 * invalidateAll() re-runs every load with cache:'no-store'. */
export function startScanWatch() {
  if (watching || typeof window === 'undefined') return;
  watching = true;

  const check = async () => {
    if (document.hidden) return;
    try {
      // 'no-cache' (not 'no-store'): revalidate with conditional headers so an
      // unchanged scan.json answers 304 instead of re-downloading ~1MB every
      // 5 minutes on a phone.
      const r = await fetch(`/data/scan.json`, { cache: 'no-cache' });
      if (!r.ok) return;
      const j = (await r.json()) as {
        generated_at?: string;
        regime?: { label?: 'risk_on' | 'risk_off' | 'mixed' };
      };
      regimeLabel.set(j.regime?.label ?? null);
      const g = j.generated_at ?? null;
      if (g && lastGeneratedAt && g !== lastGeneratedAt) {
        lastGeneratedAt = g;
        await invalidateAll();
      } else if (g) {
        lastGeneratedAt = g;
      }
    } catch {
      // offline / fetch failure — leave current data in place
    }
  };

  document.addEventListener('visibilitychange', () => void check());
  setInterval(() => void check(), 5 * 60_000);
  void check();
}
