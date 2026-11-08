/** The preference document stays bounded (decision D392). The server refuses a document over
 * 32 KB, and three keys grow with every project a person visits: the layer choices, where the
 * map was left and the feed's mark, each a map of scope (a project id or "all") to a value. The
 * document keeps the scopes visited most recently, `RECENT_SCOPES_MAX` of them, and when it is
 * still too large it lets the oldest of those go as well, never the current one, so a save
 * always lands and the choices of the projects in use stay. */

/** The server's bound is 32 KB of compact JSON; the document is kept a kilobyte under it, so
 * a key written between two saves does not tip it over. */
export const PREFERENCES_MAX_BYTES = 31 * 1024;
export const RECENT_SCOPES_MAX = 10;
/** The keys whose value is a map of scope to a value. */
export const SCOPED_KEYS = ["map_layers", "map_view", "feed_seen"] as const;
export const RECENT_SCOPES_KEY = "recent_scopes";

export type Preferences = Record<string, unknown>;

function scopedMap(
  preferences: Preferences,
  key: string,
): Record<string, unknown> | null {
  const value = preferences[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Every scope any scoped key knows, for a document from before the recency list existed. */
function knownScopes(preferences: Preferences): string[] {
  const scopes = new Set<string>();
  for (const key of SCOPED_KEYS) {
    for (const scope of Object.keys(scopedMap(preferences, key) ?? {}))
      scopes.add(scope);
  }
  return [...scopes];
}

/** The recency list as stored, or seeded from the scopes the document knows. */
export function recentScopes(preferences: Preferences): string[] {
  const stored = preferences[RECENT_SCOPES_KEY];
  if (Array.isArray(stored) && stored.every((s) => typeof s === "string"))
    return stored as string[];
  return knownScopes(preferences).slice(0, RECENT_SCOPES_MAX);
}

/** The document with `scope` as the most recent one. */
export function withRecentScope(
  preferences: Preferences,
  scope: string,
): Preferences {
  const current = recentScopes(preferences);
  if (current[0] === scope && preferences[RECENT_SCOPES_KEY] !== undefined)
    return preferences;
  const next = [scope, ...current.filter((s) => s !== scope)].slice(
    0,
    RECENT_SCOPES_MAX,
  );
  return { ...preferences, [RECENT_SCOPES_KEY]: next };
}

function keepScopes(preferences: Preferences, keep: string[]): Preferences {
  const allowed = new Set(keep);
  let changed = false;
  const next: Preferences = { ...preferences };
  for (const key of SCOPED_KEYS) {
    const map = scopedMap(preferences, key);
    if (!map) continue;
    const kept = Object.fromEntries(
      Object.entries(map).filter(([scope]) => allowed.has(scope)),
    );
    if (Object.keys(kept).length !== Object.keys(map).length) {
      next[key] = kept;
      changed = true;
    }
  }
  return changed ? next : preferences;
}

/** The size the server measures, roughly: the JSON text's length. */
export function preferencesBytes(preferences: Preferences): number {
  return JSON.stringify(preferences).length;
}

/** The document ready to save: the scoped keys trimmed to the recent scopes, and the oldest
 * of those let go while the document is over the limit; the most recent scope always stays.
 * Returns the same object when nothing had to change. */
export function prunePreferences(
  preferences: Preferences,
  limit = PREFERENCES_MAX_BYTES,
): Preferences {
  const recent = recentScopes(preferences);
  let keep = recent.slice(0, RECENT_SCOPES_MAX);
  let next = keepScopes(preferences, keep);
  while (preferencesBytes(next) > limit && keep.length > 1) {
    keep = keep.slice(0, -1);
    next = keepScopes(next, keep);
  }
  if (next !== preferences && JSON.stringify(recent) !== JSON.stringify(keep))
    next = { ...next, [RECENT_SCOPES_KEY]: keep };
  return next;
}
