import { describe, expect, it } from "vitest";

import { circlePolygon, locationFeatures } from "./networkLocations";

describe("circlePolygon", () => {
  it("draws a closed ring of the asked radius around the point", () => {
    const polygon = circlePolygon(46.5, 15.1, 64_000);
    const ring = polygon.coordinates[0];
    expect(ring.length).toBe(49);
    expect(ring[0]).toEqual(ring[48]);
    // the northernmost vertex sits one radius north: 64 km is about 0.575 degrees of latitude
    const north = Math.max(...ring.map(([, lat]) => lat));
    expect(north).toBeCloseTo(46.5 + 0.5755, 2);
    // and the ring is centred on the point
    const lons = ring.map(([lon]) => lon);
    expect((Math.min(...lons) + Math.max(...lons)) / 2).toBeCloseTo(15.1, 3);
  });
});

describe("locationFeatures", () => {
  it("turns a location point into a circle and its centre, never smaller than half a km", () => {
    const features = locationFeatures([
      {
        type: "Feature",
        id: 7,
        geometry: { type: "Point", coordinates: [15.1, 46.5] },
        properties: {
          accuracy_m: 100,
          method: "iridium_estimate",
          device_name: "SP051890",
        },
      },
    ]);
    expect(features.map((f) => f.properties?.kind)).toEqual([
      "circle",
      "centre",
    ]);
    expect(features[0].geometry.type).toBe("Polygon");
    const ring = (features[0].geometry as GeoJSON.Polygon).coordinates[0];
    const north = Math.max(...ring.map(([, lat]) => lat));
    expect(north - 46.5).toBeCloseTo(500 / 111_195, 4);
  });
});
