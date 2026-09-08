const KEY = "protect-stale-chunk-reload";
/** A second reload within this many ms would mean the reload did not help: stop then. */
const LOOP_GUARD_MS = 30_000;

/** Whether a failed page chunk should reload the page (decision D130): yes, unless a reload
 * for the same reason happened moments ago, so a real outage does not loop. */
export function shouldReloadForStaleChunk(
  now: number,
  lastReloadAt: number | null,
): boolean {
  return lastReloadAt === null || now - lastReloadAt > LOOP_GUARD_MS;
}

/** After a deploy a tab opened before it still asks for old page chunks by their hashed
 * names, which are gone: Vite reports that as `vite:preloadError`. Reload once so the new
 * index and its chunks come in, instead of a blank page until the person refreshes. */
function lastReloadAt(): number | null {
  try {
    const stored = sessionStorage.getItem(KEY);
    return stored ? Number(stored) : null;
  } catch {
    return null;
  }
}

export function reloadOnStaleChunk(): void {
  window.addEventListener("vite:preloadError", (event) => {
    if (!shouldReloadForStaleChunk(Date.now(), lastReloadAt())) return;
    event.preventDefault();
    try {
      sessionStorage.setItem(KEY, String(Date.now()));
    } catch {
      // storage may be unavailable; reload anyway
    }
    window.location.reload();
  });
}
