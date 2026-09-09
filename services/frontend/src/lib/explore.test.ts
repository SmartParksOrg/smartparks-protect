import { describe, expect, it } from "vitest";

import type { RecordRow } from "@/api/types";
import {
  boundsOfTracks,
  chartGroups,
  chartMetrics,
  nearestRowTime,
  pointsAt,
  readExploreState,
  scatterGroup,
  tracksOf,
  writeExploreState,
} from "@/lib/explore";
import { columnsOf } from "@/lib/records";

function row(
  time: string,
  device: string,
  measurements: Record<string, number | boolean>,
  position: [number, number] | null = null,
): RecordRow {
  return {
    time,
    device_id: device,
    device_name: `dev-${device}`,
    entity_id: null,
    entity_name: null,
    project_id: "p",
    position: position
      ? {
          id: 1,
          lat: position[1],
          lon: position[0],
          altitude_m: null,
          speed_mps: null,
          heading_deg: null,
          accuracy_m: null,
          satellites: null,
          valid: true,
          curated_fields: [],
          source_event_id: null,
          source_event_ingested_at: null,
          trace_id: null,
        }
      : null,
    measurements,
    state: null,
    source_event_id: null,
    source_event_ingested_at: null,
    trace_id: null,
  };
}

// newest first, as the records read gives them
const ROWS = [
  row("2026-04-01T02:00:00Z", "a", { battery_voltage: 3.9 }, [35.3, -14.9]),
  row("2026-04-01T01:00:00Z", "b", { battery_voltage: 3.7, gnss_fix: true }),
  row(
    "2026-04-01T00:00:00Z",
    "a",
    { battery_voltage: 4.1, gnss_fix: false },
    [35.1, -14.7],
  ),
];
const LABELS = new Map([
  ["battery_voltage", { label: "Battery voltage", unit: "V" }],
]);

describe("explore state", () => {
  it("reads the tabs of v2.4.0 as the table and the chart", () => {
    expect(readExploreState(new URLSearchParams("mode=records")).mode).toBe(
      "table",
    );
    expect(readExploreState(new URLSearchParams("mode=analysis")).mode).toBe(
      "chart",
    );
    expect(readExploreState(new URLSearchParams("mode=map")).mode).toBe("map");
    expect(readExploreState(new URLSearchParams("")).mode).toBe("table");
  });
  it("round-trips the chart's own state on top of the selection", () => {
    const params = new URLSearchParams(
      "mode=chart&entity=e1&range=30d&tz=UTC&metric=battery_voltage&chart=scatter&x=device_temperature&y2=activity&bucket=1h&agg=max",
    );
    const state = readExploreState(params);
    expect(state.secondary).toEqual(["activity"]);
    expect(state.metrics).toEqual(["battery_voltage"]);
    expect(state.chart).toBe("scatter");
    expect(state.xMetric).toBe("device_temperature");
    expect(state.bucket).toBe("1h");
    expect(state.aggregates).toEqual(["max"]);
    expect(writeExploreState(state).toString()).toBe(
      "mode=chart&entity=e1&range=30d&tz=UTC&metric=battery_voltage&chart=scatter&x=device_temperature&y2=activity&bucket=1h&agg=max",
    );
  });
  it("writes only what differs from the defaults", () => {
    const state = readExploreState(
      new URLSearchParams("mode=map&device=d1&tz=UTC"),
    );
    expect(writeExploreState(state).toString()).toBe(
      "mode=map&device=d1&range=7d&tz=UTC",
    );
  });
});

describe("explore data", () => {
  const columns = columnsOf(ROWS, LABELS);
  it("picks the first numeric metrics when none are chosen", () => {
    expect(chartMetrics([], columns)).toEqual(["battery_voltage"]);
    expect(chartMetrics(["battery_voltage", "nope"], columns)).toEqual([
      "battery_voltage",
    ]);
  });
  it("makes one group per metric and one series per owner, oldest first", () => {
    const groups = chartGroups(ROWS, ["battery_voltage", "gnss_fix"], columns);
    expect(groups.map((g) => [g.label, g.unit])).toEqual([
      ["Battery voltage", "V"],
      ["gnss_fix", null],
    ]);
    const a = groups[0].series.find((s) => s.ownerId === "a")!;
    expect(a.name).toBe("dev-a");
    expect(a.data).toEqual([
      [Date.parse("2026-04-01T00:00:00Z"), 4.1],
      [Date.parse("2026-04-01T02:00:00Z"), 3.9],
    ]);
    expect(groups[1].series.map((s) => s.data[0][1])).toEqual([1, 0]);
  });
  it("pairs two metrics of the same moment for a scatter", () => {
    const group = scatterGroup(ROWS, "gnss_fix", "battery_voltage", columns)!;
    expect(group.series.map((s) => s.data)).toEqual([
      [[1, 3.7, Date.parse("2026-04-01T01:00:00Z")]],
      [[0, 4.1, Date.parse("2026-04-01T00:00:00Z")]],
    ]);
    expect(scatterGroup(ROWS, "nope", "battery_voltage", columns)).toBeNull();
  });
  it("finds the nearest row to a moment in rows sorted newest first", () => {
    expect(nearestRowTime(ROWS, Date.parse("2026-04-01T00:50:00Z"))).toBe(
      "2026-04-01T01:00:00Z",
    );
    expect(nearestRowTime(ROWS, Date.parse("2026-04-01T09:00:00Z"))).toBe(
      "2026-04-01T02:00:00Z",
    );
    expect(nearestRowTime(ROWS, 0)).toBe("2026-04-01T00:00:00Z");
    expect(nearestRowTime([], 0)).toBeNull();
  });
  it("makes a track per owner from the positions, oldest first", () => {
    const tracks = tracksOf(ROWS);
    expect(tracks).toHaveLength(1);
    expect(tracks[0].entityId).toBe("a");
    expect(tracks[0].kind).toBe("device");
    expect(tracks[0].geometry).toEqual({
      type: "LineString",
      coordinates: [
        [35.1, -14.7],
        [35.3, -14.9],
      ],
    });
    expect(tracks[0].times).toEqual([
      "2026-04-01T00:00:00Z",
      "2026-04-01T02:00:00Z",
    ]);
    expect(boundsOfTracks(tracks)).toEqual([
      [35.1, -14.9],
      [35.3, -14.7],
    ]);
    expect(boundsOfTracks([])).toBeNull();
    expect(pointsAt(tracks, Date.parse("2026-04-01T01:00:00Z"))).toEqual([
      { ownerId: "a", time: "2026-04-01T00:00:00Z" },
    ]);
    expect(pointsAt(tracks, 0)).toEqual([]);
  });
});
