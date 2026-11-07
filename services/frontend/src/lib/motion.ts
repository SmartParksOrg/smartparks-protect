import { useEffect, useRef, useState, useSyncExternalStore } from "react";

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

/** True for `ms` after `busy` fell from true to false, so a row can say "received" and fade
 * where "data coming in" stood (decision D381); false on the first render and while busy. */
export function useJustFinished(
  busy: boolean,
  ms: number = DURATION.ring,
): boolean {
  const [wasBusy, setWasBusy] = useState(busy);
  // the fall counted, and the last fall whose time ran out
  const [fell, setFell] = useState(0);
  const [ended, setEnded] = useState(0);
  if (busy !== wasBusy) {
    setWasBusy(busy);
    if (!busy) setFell((n) => n + 1);
  }
  useEffect(() => {
    if (fell === 0) return;
    const timer = window.setTimeout(() => setEnded(fell), ms);
    return () => window.clearTimeout(timer);
  }, [fell, ms]);
  return fell > ended;
}

/** The number to show for `value` while it counts there (decision D383): from zero when it
 * first appears, from the number shown before when it changes, eased over `ms`; the value
 * itself at once under reduce motion or when it is not a finite number. */
export function useCountUp(
  value: number | null,
  ms: number = DURATION.count,
): number | null {
  const reduced = useReducedMotion();
  const target = value !== null && Number.isFinite(value) ? value : null;
  const [shown, setShown] = useState(0);
  const shownRef = useRef(shown);
  useEffect(() => {
    shownRef.current = shown;
  }, [shown]);
  useEffect(() => {
    if (target === null || reduced) return;
    const from = shownRef.current;
    if (from === target) return;
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      setShown(t < 1 ? from + (target - from) * easeOut(t) : target);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, reduced, ms]);
  return target === null || reduced ? target : shown;
}

/** Fast at first, settling at the end: the one easing every scripted motion uses. */
export function easeOut(t: number): number {
  const clamped = Math.max(0, Math.min(1, t));
  return 1 - (1 - clamped) ** 3;
}

/** True once `flag` has been true for `ms` without a break (decision D389): a skeleton that
 * shows only when a read is slow, never on a fast one. */
export function useDelayed(flag: boolean, ms: number): boolean {
  const [passed, setPassed] = useState(false);
  useEffect(() => {
    if (!flag) return;
    const timer = window.setTimeout(() => setPassed(true), ms);
    return () => {
      window.clearTimeout(timer);
      setPassed(false);
    };
  }, [flag, ms]);
  return flag && passed;
}

/** True for `ms` after `value` changed (decision D390), never on the first render. */
export function useJustChanged<T>(
  value: T,
  ms: number = DURATION.ring,
): boolean {
  const [seen, setSeen] = useState(value);
  const [changes, setChanges] = useState(0);
  const [ended, setEnded] = useState(0);
  if (!Object.is(value, seen)) {
    setSeen(value);
    setChanges((n) => n + 1);
  }
  useEffect(() => {
    if (changes === 0) return;
    const timer = window.setTimeout(() => setEnded(changes), ms);
    return () => window.clearTimeout(timer);
  }, [changes, ms]);
  return changes > ended;
}
