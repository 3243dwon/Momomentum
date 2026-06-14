// Scroll-reveal: the site's one shared entrance motion. An element fades and
// lifts in the first time it scrolls into view, then is forgotten. Every page
// uses this so the whole project shares one vocabulary instead of each route
// inventing (or skipping) its own.
//
// Design notes:
// - One IntersectionObserver for the whole document — cheap regardless of how
//   many elements opt in.
// - The hidden start state lives in CSS keyed on [data-reveal]; this action
//   only adds [data-revealed] when the element enters view, so CSS owns the
//   actual animation and nothing flashes hidden before hydration beyond the
//   intended entrance.
// - Reduced motion: reveal instantly with no transform and never set the
//   hidden attribute, so the transition is skipped entirely.
// - Above-the-fold elements still animate in: the observer fires for elements
//   already intersecting at observe() time, honoring their stagger delay.

type RevealParams = {
  /** Stagger offset in ms (e.g. index * 60) so lists cascade rather than pop. */
  delay?: number;
};

const reduced =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

let observer: IntersectionObserver | null = null;
const delays = new WeakMap<Element, number>();
// Safety-net timers: because [data-reveal] starts at opacity 0, content must
// never stay hidden if the observer fails to fire for any reason. Each element
// also gets a timer that reveals it unconditionally; the observer clears it on
// a normal reveal.
const fallbacks = new WeakMap<Element, ReturnType<typeof setTimeout>>();
const FALLBACK_MS = 1500;

function show(el: HTMLElement, withDelay: boolean) {
  const delay = delays.get(el) ?? 0;
  if (withDelay && delay) el.style.transitionDelay = `${delay}ms`;
  el.setAttribute('data-revealed', '');
  const t = fallbacks.get(el);
  if (t) clearTimeout(t);
  fallbacks.delete(el);
  delays.delete(el);
  observer?.unobserve(el);
}

function ensureObserver(): IntersectionObserver | null {
  if (observer || typeof window === 'undefined' || !('IntersectionObserver' in window)) {
    return observer;
  }
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) show(entry.target as HTMLElement, true);
      }
    },
    // Fire a touch before the element is fully on screen, as soon as a sliver shows.
    { rootMargin: '0px 0px -8% 0px', threshold: 0.01 }
  );
  return observer;
}

/** Svelte action: `<div use:reveal>` or `<div use:reveal={{ delay: i * 60 }}>`. */
export function reveal(node: HTMLElement, params: RevealParams = {}) {
  // Reduced motion (or no IO support): show immediately, no entrance.
  const obs = ensureObserver();
  if (reduced || !obs) {
    node.setAttribute('data-revealed', '');
    return {};
  }
  node.setAttribute('data-reveal', '');
  delays.set(node, params.delay ?? 0);
  obs.observe(node);
  // Unconditional fallback so content can never get stuck invisible.
  fallbacks.set(
    node,
    setTimeout(() => show(node, false), FALLBACK_MS)
  );
  return {
    update(next: RevealParams = {}) {
      delays.set(node, next.delay ?? 0);
    },
    destroy() {
      const t = fallbacks.get(node);
      if (t) clearTimeout(t);
      fallbacks.delete(node);
      obs.unobserve(node);
      delays.delete(node);
    }
  };
}
