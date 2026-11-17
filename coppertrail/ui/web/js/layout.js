// Window-width breakpoints (HANDOVER 8b "Resizing"), the same numbers as tokens.BREAKPOINTS
// and the media queries in css/frame.css, css/filterbar.css and css/layout.css.
// Most of the responsive layout is CSS; this is for JS that has to know (tile counts, charts).

export const COMPACT_MAX = 1440;
export const ULTRAWIDE_MIN = 2400;

const compact = window.matchMedia(`(max-width: ${COMPACT_MAX}px)`);
const ultrawide = window.matchMedia(`(min-width: ${ULTRAWIDE_MIN}px)`);

/** "compact" (<= 1440 px), "ultrawide" (>= 2400 px) or "base". */
export function breakpoint() {
  if (compact.matches) return "compact";
  if (ultrawide.matches) return "ultrawide";
  return "base";
}

/** Calls fn(breakpoint) whenever the window crosses a breakpoint; returns an unsubscribe. */
export function onBreakpoint(fn) {
  const handler = () => fn(breakpoint());
  compact.addEventListener("change", handler);
  ultrawide.addEventListener("change", handler);
  return () => {
    compact.removeEventListener("change", handler);
    ultrawide.removeEventListener("change", handler);
  };
}
