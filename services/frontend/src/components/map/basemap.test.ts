import { describe, expect, it } from "vitest";

import {
  basemapsFor,
  basemapStyle,
  FREE_BASEMAPS,
} from "@/components/map/basemap";

describe("base maps", () => {
  it("offers satellite only with a MapTiler key", () => {
    expect(Object.keys(basemapsFor(null))).toEqual([
      "liberty",
      "positron",
      "bright",
    ]);
    const withKey = basemapsFor("abc");
    expect(Object.keys(withKey)).toContain("satellite");
    expect(withKey.satellite.style).toBe(
      "https://api.maptiler.com/maps/hybrid/style.json?key=abc",
    );
  });

  it("falls back to Light for a choice the server does not offer", () => {
    expect(basemapStyle("satellite", basemapsFor(null))).toBe(
      FREE_BASEMAPS.positron.style,
    );
    expect(basemapStyle("bright", basemapsFor(null))).toBe(
      FREE_BASEMAPS.bright.style,
    );
  });
});
