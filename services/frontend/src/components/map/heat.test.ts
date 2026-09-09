import { describe, expect, it } from "vitest";

import {
  clampRadius,
  DEFAULT_HEAT,
  heatScopeOf,
  intensityFor,
  metresPerPixel,
  parseHeatSettings,
  radiusExpression,
} from "@/components/map/heat";

describe("heatmap settings", () => {
  it("reads the URL with the defaults for what is missing and clamps the rest", () => {
    const params = new URLSearchParams(
      "heat_radius=99999&heat_sensitivity=9&heat_hours=48",
    );
    expect(parseHeatSettings(params, DEFAULT_HEAT)).toEqual({
      radius_m: 5000,
      sensitivity: 5,
      hours: 48,
    });
    expect(
      parseHeatSettings(new URLSearchParams(""), {
        radius_m: 80,
        sensitivity: 2,
        hours: 6,
      }),
    ).toEqual({
      radius_m: 80,
      sensitivity: 2,
      hours: 6,
    });
    expect(clampRadius(Number.NaN)).toBe(DEFAULT_HEAT.radius_m);
    expect(clampRadius(1)).toBe(10);
    expect(heatScopeOf(new URLSearchParams("heat_scope=selected"))).toBe(
      "selected",
    );
    expect(heatScopeOf(new URLSearchParams(""))).toBe("shown");
  });

  it("turns metres into pixels per zoom at the map's latitude", () => {
    // at the equator and zoom 0 one pixel is about 156 km
    expect(metresPerPixel(0, 0)).toBeCloseTo(156543, 0);
    const expression = radiusExpression(250, 52);
    expect(expression.slice(0, 3)).toEqual([
      "interpolate",
      ["exponential", 2],
      ["zoom"],
    ]);
    const stops = expression.slice(3) as number[];
    const at = (zoom: number) => stops[stops.indexOf(zoom) + 1];
    expect(at(0)).toBe(6); // clamped to the floor
    expect(at(14)).toBeCloseTo(250 / metresPerPixel(52, 14), 3);
    expect(at(22)).toBe(200); // clamped to the ceiling
  });

  it("maps sensitivity to a rising intensity", () => {
    expect(intensityFor(1)).toBeLessThan(intensityFor(3));
    expect(intensityFor(3)).toBeLessThan(intensityFor(5));
    expect(intensityFor(42)).toBe(intensityFor(5));
  });
});
