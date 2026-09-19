import { describe, expect, it } from "vitest";

import { boundsOf, geometryBounds } from "@/components/map/fit";

const point = (lon: number, lat: number) => ({
  geometry: { type: "Point", coordinates: [lon, lat] },
});

describe("boundsOf", () => {
  it("spans entities and devices together and skips features without a position", () => {
    expect(
      boundsOf([
        point(31.5, -24.9),
        { geometry: null },
        point(31.7, -24.8),
        point(31.6, -25.0),
      ]),
    ).toEqual([
      [31.5, -25.0],
      [31.7, -24.8],
    ]);
  });

  it("is null without any position, so the map keeps its view", () => {
    expect(boundsOf([])).toBeNull();
    expect(boundsOf([{ geometry: null }, { geometry: undefined }])).toBeNull();
  });

  it("gives a point extent for one feature", () => {
    expect(boundsOf([point(31.5, -24.9)])).toEqual([
      [31.5, -24.9],
      [31.5, -24.9],
    ]);
  });
});

describe("geometryBounds", () => {
  it("spans lines and polygons as well as points", () => {
    const bounds = geometryBounds([
      { geometry: { type: "Point", coordinates: [4.6, 52.5] } },
      {
        geometry: {
          type: "LineString",
          coordinates: [
            [4.7, 52.4],
            [4.8, 52.6],
          ],
        },
      },
      {
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [4.5, 52.55],
              [4.55, 52.55],
              [4.55, 52.7],
              [4.5, 52.55],
            ],
          ],
        },
      },
      { geometry: null },
    ]);
    expect(bounds).toEqual([
      [4.5, 52.4],
      [4.8, 52.7],
    ]);
    expect(geometryBounds([{ geometry: null }])).toBeNull();
  });
});
