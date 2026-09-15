/** Helpers of the live map's stream handling (Tim, 2026-09-15), pure so they are testable. */

/** Whether an incoming position is at least as new as the one shown: a raw log decoded while
 * the map is open carries old positions, and those must not move a marker back in time. */
export function isNewer(shown: string | null | undefined, incoming: string): boolean {
  if (!shown) return true;
  const before = Date.parse(shown);
  const after = Date.parse(incoming);
  if (!Number.isFinite(before) || !Number.isFinite(after)) return true;
  return after >= before;
}

/** Runs a keyed action once a burst of calls has gone quiet for `delayMs`: a thousand
 * positions from one file refetch the tracks once, not a thousand times. */
export function createSettler(delayMs: number) {
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  return (key: string, run: () => void): void => {
    if (timers.has(key)) return;
    timers.set(
      key,
      setTimeout(() => {
        timers.delete(key);
        run();
      }, delayMs),
    );
  };
}
