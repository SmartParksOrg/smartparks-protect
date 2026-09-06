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
