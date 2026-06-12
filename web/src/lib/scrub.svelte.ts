// Scroll-scrub primitive for the pinned story stages (/review trial, /anatomy).
// Maps a tall wrapper's traversal to a smoothed 0..1 progress; every visual
// downstream derives from `progress`, so scenes are reversible by construction.
// The rAF lerp smooths wheel-step input without touching native scrolling.
export class Scrub {
  progress = $state(0);

  /** Svelte action for the tall track element. */
  attach = (node: HTMLElement) => {
    let raf = 0;
    let target = 0;
    let settled = true;

    const measure = () => {
      const span = node.offsetHeight - window.innerHeight;
      const top = node.getBoundingClientRect().top;
      target = span > 0 ? Math.min(1, Math.max(0, -top / span)) : 0;
    };

    const tick = () => {
      const d = target - this.progress;
      if (Math.abs(d) < 0.001) {
        this.progress = target;
        settled = true;
        return;
      }
      this.progress += d * 0.18;
      raf = requestAnimationFrame(tick);
    };

    const wake = () => {
      measure();
      if (settled) {
        settled = false;
        raf = requestAnimationFrame(tick);
      }
    };

    measure();
    this.progress = target; // mid-page reloads land on the right frame
    window.addEventListener('scroll', wake, { passive: true });
    window.addEventListener('resize', wake, { passive: true });

    return {
      destroy() {
        window.removeEventListener('scroll', wake);
        window.removeEventListener('resize', wake);
        cancelAnimationFrame(raf);
      }
    };
  };
}

/** Linear ramp of progress p across [a, b], clamped to 0..1. */
export function phase(p: number, a: number, b: number): number {
  if (b <= a) return p >= b ? 1 : 0;
  return Math.min(1, Math.max(0, (p - a) / (b - a)));
}

/** Static-fallback check: pinned scenes render their final frame instead. */
export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
