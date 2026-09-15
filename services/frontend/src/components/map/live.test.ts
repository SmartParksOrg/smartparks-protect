import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createSettler, isNewer } from "@/components/map/live";

describe("isNewer", () => {
  it("accepts a position newer than or equal to the one shown, and anything when none is shown", () => {
    expect(isNewer("2026-09-15T10:00:00+00:00", "2026-09-15T10:05:00Z")).toBe(true);
    expect(isNewer("2026-09-15T10:00:00+00:00", "2026-09-15T10:00:00Z")).toBe(true);
    expect(isNewer(null, "2025-05-15T19:28:47Z")).toBe(true);
  });
  it("refuses an older position, the case of a raw log decoded while the map is open", () => {
    expect(isNewer("2026-09-15T10:00:00Z", "2025-05-15T19:28:47Z")).toBe(false);
  });
});

describe("createSettler", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  it("runs a key once after a burst and keeps keys apart", () => {
    const settle = createSettler(5000);
    const track = vi.fn();
    const heat = vi.fn();
    for (let i = 0; i < 100; i++) settle("track", track);
    settle("heat", heat);
    vi.advanceTimersByTime(4999);
    expect(track).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(track).toHaveBeenCalledTimes(1);
    expect(heat).toHaveBeenCalledTimes(1);
    settle("track", track);
    vi.advanceTimersByTime(5000);
    expect(track).toHaveBeenCalledTimes(2);
  });
});
