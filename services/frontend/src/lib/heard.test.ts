import { describe, expect, it } from "vitest";

import type { CoverageResponse } from "@/api/types";
import { listParam, mergeCoverage, toggleId } from "@/lib/heard";

const point = (id: number) =>
  ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [16, -20] },
    properties: { id, best_rssi: -100, gateways: 1, time: "2026-11-06T00:00:00Z" },
  }) as unknown as Record<string, unknown>;
const path = (gateway: string) =>
  ({
    type: "Feature",
    geometry: { type: "MultiLineString", coordinates: [] },
    properties: { kind: "path", gateway, receptions: 1 },
  }) as unknown as Record<string, unknown>;
const response = (features: Record<string, unknown>[], total: number): CoverageResponse => ({
  hours: 168,
  mode: "points",
  hexagon_m: null,
  total,
  features,
  gateways: [],
});

describe("the heard toggles in the URL", () => {
  it("reads a comma list and toggles an id", () => {
    expect(listParam(new URLSearchParams("heard=a,b"), "heard")).toEqual(["a", "b"]);
    expect(listParam(new URLSearchParams(""), "heard")).toEqual([]);
    expect(toggleId(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleId(["a", "b"], "a")).toEqual(["b"]);
  });
});

describe("mergeCoverage", () => {
  it("draws a position answered by both reads once and keeps both paths", () => {
    const view = response([point(1), point(2), path("gw-a")], 2);
    const selected = response([point(2), point(3), path("gw-b")], 2);
    const merged = mergeCoverage(view, selected);
    expect(merged.points).toBe(3);
    expect(merged.total).toBe(3);
    expect(merged.features.filter((f) => f.geometry?.type === "MultiLineString")).toHaveLength(2);
  });

  it("passes one read through", () => {
    const only = mergeCoverage(undefined, response([point(1)], 5));
    expect(only.points).toBe(1);
    expect(only.total).toBe(5);
    expect(mergeCoverage(undefined, undefined)).toEqual({ features: [], total: 0, points: 0 });
  });
});
