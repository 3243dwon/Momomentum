// Pointer-tilt: a card leans toward the cursor in 3D, easing back when the
// pointer leaves. Subtle by default (max ~6°) so it reads as responsiveness,
// not a gimmick. The visual transform lives in CSS (.tilt); this action only
// feeds it --tilt-x/--tilt-y and toggles [data-tilting] (which drops the
// transform transition so the lean tracks the cursor without lag).
//
// No-op for touch pointers and reduced motion — those never get a lean, and the
// CSS .tilt stays flat because the custom props are never driven off zero.

const reduced =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const canHover = typeof window !== 'undefined' && window.matchMedia('(hover: hover)').matches;

export function tilt(node: HTMLElement, max = 6) {
  if (reduced || !canHover) return {};

  let raf = 0;
  let limit = max;

  const onMove = (e: PointerEvent) => {
    const r = node.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5; // -0.5..0.5
    const py = (e.clientY - r.top) / r.height - 0.5;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      node.style.setProperty('--tilt-x', `${(px * 2 * limit).toFixed(2)}deg`);
      node.style.setProperty('--tilt-y', `${(-py * 2 * limit).toFixed(2)}deg`);
    });
  };
  const onEnter = () => node.setAttribute('data-tilting', '');
  const onLeave = () => {
    cancelAnimationFrame(raf);
    node.removeAttribute('data-tilting'); // restores the ease-back transition
    node.style.setProperty('--tilt-x', '0deg');
    node.style.setProperty('--tilt-y', '0deg');
  };

  node.addEventListener('pointerenter', onEnter);
  node.addEventListener('pointermove', onMove);
  node.addEventListener('pointerleave', onLeave);

  return {
    update(next = 6) {
      limit = next;
    },
    destroy() {
      cancelAnimationFrame(raf);
      node.removeEventListener('pointerenter', onEnter);
      node.removeEventListener('pointermove', onMove);
      node.removeEventListener('pointerleave', onLeave);
    }
  };
}
