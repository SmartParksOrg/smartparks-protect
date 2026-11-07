import { useSyncExternalStore } from "react";

/** Motion that explains, never decorates (decision D378, ADR 0042): a thing moves because it
 * came from somewhere, changed, or is working. The durations every animation of the app takes,
 * in milliseconds, and the one switch that stops them all: the operating system's reduce-motion
 * setting. CSS reads the setting itself (the rule in `index.css`); the map's loop and the
 * charts read it through `useReducedMotion`. */
export const DURATION = {
  /** An overlay or a panel entering, a badge changing colour, a tab's content. */
  interface: 200,
  /** A marker gliding to its new fix. */
  glide: 600,
  /** The ring that expands once from a new fix. */
  ring: 1200,
  /** A chart drawing in or morphing into its new series. */
  chart: 300,
  /** A number counting to its value. */
  count: 400,
} as const;

const QUERY = "(prefers-reduced-motion: reduce)";

/** Whether the person asked their operating system for less motion; false where the browser
 * cannot say (a test's jsdom has no `matchMedia`). */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(QUERY).matches
  );
}

const subscribe = (onChange: () => void) => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function")
    return () => {};
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
};

/** The reduce-motion setting as React state, so a component re-renders when it changes. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}
