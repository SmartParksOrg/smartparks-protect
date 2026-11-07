import { useEffect, useState } from "react";

/** The current time, re-rendered every `intervalMs` (phase 15): pages that show "3 min ago"
 * pass it to `formatAgo` so the text moves without refetching anything. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** A clock that ticks every second while any of `values` is under a minute old, so "just now"
 * and "23 s ago" count (decision D387), and leans on `base` (a parent's 30 s clock) or its
 * own 30 s rhythm otherwise. Only the component showing the fresh moment re-renders. */
export function useLiveNow(
  values: (string | null | undefined)[],
  base?: number,
): number {
  const [fast, setFast] = useState(false);
  const tick = useNow(fast ? 1_000 : 30_000);
  const now = fast ? tick : (base ?? tick);
  const recent = values.some(
    (v) => v && Math.abs(now - new Date(v).getTime()) < 60_000,
  );
  if (recent !== fast) setFast(recent);
  return now;
}
