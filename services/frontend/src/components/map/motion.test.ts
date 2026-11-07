import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  glidedCoordinates,
  glideKey,
  inMotion,
  resetMotion,
  startGlide,
} from "@/components/map/motion";
import { DURATION } from "@/lib/motion";

beforeEach(() => {
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 1),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => {
  resetMotion();
  vi.unstubAllGlobals();
});

const key = glideKey("entity", "e1");

describe("startGlide and glidedCoordinates", () => {
  it("is the spot itself without a glide", () => {
    expect(glidedCoordinates(key, [16, -20], 0)).toEqual([16, -20]);
    expect(inMotion()).toBe(false);
  });
  it("moves between the two spots and lands at the end", () => {
    startGlide(key, [16, -20], [17, -21], 1000);
    expect(glidedCoordinates(key, [17, -21], 1000)).toEqual([16, -20]);
    const [lng, lat] = glidedCoordinates(
      key,
      [17, -21],
      1000 + DURATION.glide / 2,
    );
    expect(lng).toBeGreaterThan(16.5);
    expect(lng).toBeLessThan(17);
    expect(lat).toBeLessThan(-20.5);
    expect(glidedCoordinates(key, [17, -21], 1000 + DURATION.glide)).toEqual([
      17, -21,
    ]);
    expect(inMotion()).toBe(true);
  });
  it("starts nothing for the same spot", () => {
    startGlide(key, [16, -20], [16, -20], 1000);
    expect(inMotion()).toBe(false);
  });
  it("starts again from where the marker is now", () => {
    startGlide(key, [16, -20], [18, -20], 1000);
    const midway = 1000 + DURATION.glide / 2;
    const [before] = glidedCoordinates(key, [18, -20], midway);
    startGlide(key, [16, -20], [10, -20], midway);
    expect(glidedCoordinates(key, [10, -20], midway)[0]).toBeCloseTo(before, 6);
  });
});
