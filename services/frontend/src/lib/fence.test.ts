import { describe, expect, it } from "vitest";

import type { Feature } from "@/api/types";
import {
  fenceRuns,
  fenceSectionFeatures,
  fenceSummary,
  sliceLine,
} from "@/lib/fence";

const LINE = [
  [4.6, 52.5],
  [4.6147, 52.5],
  [4.6147, 52.5045],
];

describe("a fence line on the map", () => {
  it("slices a line by metres along it", () => {
    const first = sliceLine(LINE, 0, 500);
    expect(first[0]).toEqual([4.6, 52.5]);
    expect(first[first.length - 1][0]).toBeGreaterThan(4.6);
    expect(first[first.length - 1][0]).toBeLessThan(4.6147);
    const corner = sliceLine(LINE, 800, 1200);
    expect(corner.length).toBe(3);
    expect(corner[1]).toEqual([4.6147, 52.5]);
  });

  it("draws one piece per section, each with its level", () => {
    const feature = {
      id: "f",
      name: "East",
      feature_type: "fence",
      geometry: { type: "LineString", coordinates: LINE },
      fence_level: "low",
      fence_sections: [
        { from_m: 0, to_m: 400, level: "ok" },
        { from_m: 400, to_m: 1500, level: "low" },
      ],
    } as unknown as Feature;
    const pieces = fenceSectionFeatures(feature);
    expect(pieces.map((p) => p.properties?.fence_level)).toEqual(["ok", "low"]);
    expect(pieces[0].geometry.type).toBe("LineString");
  });

  it("leaves a route as it is", () => {
    const route = {
      id: "r",
      name: "Patrol",
      feature_type: "route",
      geometry: { type: "LineString", coordinates: LINE },
    } as unknown as Feature;
    expect(fenceSectionFeatures(route)).toHaveLength(1);
  });
});

describe("the fence summary sentence", () => {
  const t = (key: string, o?: Record<string, unknown>) =>
    key.replace(/\{\{(\w+)\}\}/g, (_, k) => String(o?.[k]));
  const monitors = [
    { entity_id: "a", name: "North gate", level: "ok" },
    { entity_id: "b", name: "Middle", level: "low" },
    { entity_id: "c", name: "South corner", level: "down" },
  ];
  it("names the worst stretch and counts its sections", () => {
    const sections = [
      { from_m: 0, to_m: 400, level: "ok", monitor_ids: ["a"] },
      { from_m: 400, to_m: 1100, level: "low", monitor_ids: ["a", "b"] },
      { from_m: 1100, to_m: 2200, level: "down", monitor_ids: ["b", "c"] },
      { from_m: 2200, to_m: 2900, level: "down", monitor_ids: ["c"] },
    ];
    expect(fenceSummary(sections, monitors, t)).toBe(
      "2 of 4 sections down, Middle to South corner",
    );
    expect(fenceRuns(sections).map((r) => r.level)).toEqual([
      "ok",
      "low",
      "down",
    ]);
  });
  it("says all is well when it is", () => {
    const sections = [
      { from_m: 0, to_m: 400, level: "ok", monitor_ids: ["a"] },
      { from_m: 400, to_m: 900, level: "ok", monitor_ids: ["a", "b"] },
    ];
    expect(fenceSummary(sections, monitors, t)).toBe("all 2 sections live");
  });
  it("says so when nothing is on the line", () => {
    expect(
      fenceSummary([{ from_m: 0, to_m: 1, level: "unknown" }], [], t),
    ).toBe("No fence monitor on this line yet.");
  });
});
