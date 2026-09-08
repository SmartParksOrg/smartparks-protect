import { describe, expect, it } from "vitest";

import { shouldReloadForStaleChunk } from "@/lib/staleChunk";

describe("stale chunk reload", () => {
  it("reloads the first time and again after the guard, not in a loop", () => {
    const now = 1_000_000;
    expect(shouldReloadForStaleChunk(now, null)).toBe(true);
    expect(shouldReloadForStaleChunk(now, now - 5_000)).toBe(false);
    expect(shouldReloadForStaleChunk(now, now - 60_000)).toBe(true);
  });
});
