import { describe, expect, it } from "vitest";

import { accuracyCircles } from "./layers";

const point = (
  accuracy: number | null,
  lon = 5.36,
  lat = 52.09,
): GeoJSON.Feature => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [lon, lat] },
  properties: { accuracy_m: accuracy },
});

describe("accuracyCircles", () => {
  it("draws a disc only for a position known to be imprecise", () => {
    const discs = accuracyCircles([
      point(455),
      point(8),
      point(null),
      point(60),
    ]);
    expect(discs).toHaveLength(2);
    expect(discs[0].geometry.type).toBe("Polygon");
    expect(discs.map((d) => d.properties?.accuracy_m)).toEqual([455, 60]);
  });
});
