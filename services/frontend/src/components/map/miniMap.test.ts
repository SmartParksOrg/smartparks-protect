import { describe, expect, it } from "vitest";

import type { Position } from "@/api/types";
import { miniMapGeometry } from "@/components/map/miniMap";

const at = (lon: number, lat: number, geometry = true) =>
  ({
    geometry: geometry ? { type: "Point", coordinates: [lon, lat] } : null,
  }) as unknown as Position;

describe("mini map geometry", () => {
  it("draws the trail oldest first and marks the newest", () => {
    const g = miniMapGeometry([at(5.3, 52.1), at(5.2, 52.0), at(5.1, 51.9)]);
    expect(g?.latest).toEqual([5.3, 52.1]);
    expect(g?.line).toEqual([
      [5.1, 51.9],
      [5.2, 52.0],
      [5.3, 52.1],
    ]);
    expect(g?.bounds).toEqual([5.1, 51.9, 5.3, 52.1]);
  });

  it("skips positions without coordinates and gives null for none", () => {
    expect(miniMapGeometry([at(0, 0, false)])).toBeNull();
    expect(miniMapGeometry([at(1, 2, false), at(3, 4)])?.latest).toEqual([
      3, 4,
    ]);
  });
});
