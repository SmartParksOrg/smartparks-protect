import { describe, expect, it } from "vitest";

import {
  prunePreferences,
  recentScopes,
  RECENT_SCOPES_MAX,
  withRecentScope,
} from "@/lib/preferences";

const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;

describe("the preference document stays bounded (decision D392)", () => {
  it("keeps the most recent scope first, once, and at most ten", () => {
    let prefs: Record<string, unknown> = {};
    for (let i = 1; i <= 12; i++) prefs = withRecentScope(prefs, id(i));
    prefs = withRecentScope(prefs, id(5));
    const recent = recentScopes(prefs);
    expect(recent[0]).toBe(id(5));
    expect(recent).toHaveLength(RECENT_SCOPES_MAX);
    expect(recent).not.toContain(id(1));
    expect(recent.filter((s) => s === id(5))).toHaveLength(1);
  });

  it("seeds the list from the scopes an older document knows", () => {
    const prefs = {
      map_view: { all: [1, 2, 3], [id(1)]: [4, 5, 6] },
      map_layers: { [id(2)]: { features: false } },
    };
    expect(recentScopes(prefs).sort()).toEqual(["all", id(1), id(2)].sort());
    const noted = withRecentScope(prefs, id(2));
    expect(recentScopes(noted)[0]).toBe(id(2));
    expect(recentScopes(noted)).toHaveLength(3);
  });

  it("drops the scopes that are not recent from every scoped key and leaves the rest", () => {
    let prefs: Record<string, unknown> = {
      theme: "dark",
      map_view: Object.fromEntries(
        [...Array(15)].map((_, i) => [id(i), [i, i, 1]]),
      ),
      map_layers: { [id(0)]: { features: false }, [id(14)]: { events: false } },
      feed_seen: { [id(3)]: "2026-11-08T00:00:00Z" },
    };
    for (let i = 14; i >= 5; i--) prefs = withRecentScope(prefs, id(i));
    const pruned = prunePreferences(prefs);
    expect(Object.keys(pruned.map_view as object)).toHaveLength(10);
    expect(pruned.map_layers).toEqual({ [id(14)]: { events: false } });
    expect(pruned.feed_seen).toEqual({});
    expect(pruned.theme).toBe("dark");
  });

  it("lets the oldest recent scopes go while the document is over the limit, never the current one", () => {
    const big = [...Array(300)].map((_, i) => id(i));
    let prefs: Record<string, unknown> = {
      map_layers: {
        all: { shown_devices: big },
        [id(1)]: { shown_devices: big.slice(0, 100) },
        [id(2)]: { hidden_entities: big.slice(0, 50) },
      },
    };
    prefs = withRecentScope(prefs, id(2));
    prefs = withRecentScope(prefs, id(1));
    prefs = withRecentScope(prefs, "all");
    const pruned = prunePreferences(prefs, 14_000);
    const layers = pruned.map_layers as Record<string, unknown>;
    expect(Object.keys(layers)).toEqual(["all"]);
    expect(recentScopes(pruned)).toEqual(["all"]);
    expect(JSON.stringify(pruned).length).toBeLessThanOrEqual(14_000);
  });

  it("returns the same object when nothing has to change", () => {
    const prefs = withRecentScope({ map_view: { all: [1, 2, 3] } }, "all");
    expect(prunePreferences(prefs)).toBe(prefs);
  });
});
