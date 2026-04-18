// Formatting helpers used across the UI.

export function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '–';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)}%`;
}

export function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '–';
  return n >= 1000 ? n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : n.toFixed(2);
}

export function fmtVolume(n: number | null | undefined): string {
  if (n == null) return '–';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

export function fmtRelVol(n: number | null | undefined): string {
  if (n == null) return '–';
  return `${n.toFixed(2)}x`;
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '–';
  const t = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.round((now - t) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short'
  });
}

export function pctClass(n: number | null | undefined): string {
  if (n == null) return 'text-zinc-400';
  if (n > 0) return 'text-signal-up';
  if (n < 0) return 'text-signal-down';
  return 'text-zinc-400';
}

export function impactPill(impact?: string): string {
  switch (impact) {
    case 'high':
      return 'pill-warn';
    case 'medium':
      return 'pill-info';
    case 'low':
      return 'pill-flat';
    default:
      return 'pill-flat';
  }
}

export function confidencePill(c?: string): string {
  switch (c) {
    case 'high':
      return 'pill-up';
    case 'medium':
      return 'pill-info';
    case 'low':
      return 'pill-flat';
    default:
      return 'pill-flat';
  }
}
