import { describe, expect, it } from "vitest";

import { boundsOf } from "@/components/map/fit";

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
