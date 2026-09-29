import { describe, expect, it } from "vitest";

import {
  PRESSURE_RAMP,
  SPEED_BAND_EDGES_KMH,
  SPEED_BAND_LABELS,
  SPEED_RAMP,
  boundsOfFeatures,
  decorateAnalysisFeatures,
  overLimit,
  pressureColor,
  speedColor,
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
  it("colours an area by its relative pressure and draws it under the rest", () => {
    const square = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
      [0, 0],
    ];
    const decorated = decorateAnalysisFeatures(
      [feature("hotspot", 0.3, "a", square), feature("area", 2.4, "", square)],
      () => "#111111",
    );
    expect(decorated[0].properties?.kind).toBe("area");
    expect(decorated[0].properties?.color).toBe(PRESSURE_RAMP[4]);
    expect(pressureColor(null)).toBe(PRESSURE_RAMP[0]);
    expect(pressureColor(1)).toBe(PRESSURE_RAMP[2]);
    expect(pressureColor(0.5)).toBe(PRESSURE_RAMP[1]);
  });
  it("colours a trip's path by its speed, outlines it over the limit, and its markers by kind", () => {
    expect(SPEED_RAMP).toHaveLength(SPEED_BAND_EDGES_KMH.length + 1);
    expect(SPEED_BAND_LABELS).toHaveLength(SPEED_RAMP.length);
    expect(
      [5, 10, 39.9, 79, 100, 130].map((v) =>
        SPEED_RAMP.indexOf(speedColor(v) as (typeof SPEED_RAMP)[number]),
      ),
    ).toEqual([0, 1, 2, 3, 4, 5]);
    expect(speedColor(null)).toBe(SPEED_RAMP[0]);
    // the module says which side of the limit a stretch was on; an older run's speed does
    expect(overLimit({ over_limit: false, speed_kmh: 90, limit_kmh: 60 })).toBe(
      false,
    );
    expect(overLimit({ speed_kmh: 90, limit_kmh: 60 })).toBe(true);
    expect(overLimit({ speed_kmh: 60, limit_kmh: 60 })).toBe(false);
    expect(overLimit(null)).toBe(false);
    const line: GeoJSON.Feature = {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [0, 0],
          [1, 1],
        ],
      },
      properties: {
        kind: "trip_segment",
        level: 1.3,
        subject_id: "a",
        speed_kmh: 78,
        limit_kmh: 60,
      },
    };
    const start: GeoJSON.Feature = {
      type: "Feature",
      geometry: { type: "Point", coordinates: [0, 0] },
      properties: {
        kind: "trip_marker",
        subject_id: "a",
        short: "1",
        role: "start",
      },
    };
    const [l, s] = decorateAnalysisFeatures([line, start], () => "#111111");
    // 78 km/h is the band from 40, whatever the limit; the limit of 60 gives the outline
    expect(l.properties?.color).toBe(SPEED_RAMP[3]);
    expect(l.properties?.over).toBe(true);
    expect(s.properties?.color).toBe("#52735E");
    expect(s.properties?.over).toBeUndefined();
    const [e] = decorateAnalysisFeatures(
      [{ ...start, properties: { ...start.properties, role: "end" } }],
      () => "#111111",
    );
    expect(e.properties?.color).toBe("#1F2A24");
  });
});
