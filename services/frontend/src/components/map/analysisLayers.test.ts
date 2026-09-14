import { describe, expect, it } from "vitest";

import {
  boundsOfFeatures,
  decorateAnalysisFeatures,
} from "./analysisLayers";

const feature = (
  kind: string,
  level: number,
  subject: string,
  ring: number[][],
): GeoJSON.Feature => ({
  type: "Feature",
  geometry: { type: "Polygon", coordinates: [ring] },
  properties: { kind, level, subject_id: subject },
});

describe("analysis layers", () => {
  it("colours by subject and draws the larger polygons first", () => {
    const square = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
      [0, 0],
    ];
    const decorated = decorateAnalysisFeatures(
      [
        feature("hotspot", 0.3, "a", square),
        feature("kde", 0.5, "a", square),
        feature("kde", 0.95, "b", square),
        feature("mcp", 0.95, "a", square),
      ],
      (id) => (id === "a" ? "#111111" : "#222222"),
    );
    expect(decorated.map((f) => f.properties?.kind)).toEqual([
      "mcp",
      "kde",
      "kde",
      "hotspot",
    ]);
    expect(decorated[1].properties?.level).toBe(0.95);
    expect(decorated[0].properties?.color).toBe("#111111");
    expect(decorated[1].properties?.color).toBe("#222222");
    expect(decorated[3].properties?.opacity).toBeGreaterThan(
      decorated[0].properties?.opacity as number,
    );
  });
  it("finds the bounds of polygons and multipolygons", () => {
    const bounds = boundsOfFeatures([
      feature("mcp", 1, "a", [
        [10, -20],
        [11, -20],
        [11, -19],
        [10, -19],
        [10, -20],
      ]),
      {
        type: "Feature",
        geometry: {
          type: "MultiPolygon",
          coordinates: [
            [
              [
                [12, -22],
                [12.5, -22],
                [12.5, -21.5],
                [12, -22],
              ],
            ],
          ],
        },
        properties: {},
      },
    ]);
    expect(bounds).toEqual([
      [10, -22],
      [12.5, -19],
    ]);
    expect(boundsOfFeatures([])).toBeNull();
  });
});
