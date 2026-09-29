import { describe, expect, it } from "vitest";

import type { SeriesResponse } from "@/api/types";
import {
  inReadUnits,
  metricRows,
  metricTileQuery,
  readMetricOptions,
  tileNumber,
  writeMetricOptions,
} from "@/lib/dashboards";

const WINDOW = {
  from: "2026-09-22T00:00:00.000Z",
  to: "2026-09-29T00:00:00.000Z",
};

describe("a dashboard's metric tile", () => {
  it("reads stored options with their defaults and drops what it does not know", () => {
    expect(readMetricOptions(null)).toMatchObject({
      metrics: [],
      group_by: "entity",
      range: "7d",
      aggregate: "mean",
      display: "line",
    });
    const read = readMetricOptions({
      metrics: ["speed", 7, "heading"],
      entity_ids: ["a"],
      range: "2w",
      aggregate: "mode",
      display: "pie",
      group_by: "device",
    });
    expect(read.metrics).toEqual(["speed", "heading"]);
    expect(read.group_by).toBe("device");
    expect([read.range, read.aggregate, read.display]).toEqual([
      "7d",
      "mean",
      "line",
    ]);
  });

  it("writes the subjects of its own kind and one metric for a number", () => {
    const written = writeMetricOptions({
      ...readMetricOptions({
        metrics: ["speed", "heading"],
        entity_ids: ["a"],
        device_ids: ["d"],
        display: "number",
      }),
    });
    expect(written.metrics).toEqual(["speed"]);
    expect(written.entity_ids).toEqual(["a"]);
    expect(written.device_ids).toEqual([]);
  });

  it("asks a graph per bucket and a table over the whole period", () => {
    const graph = new URLSearchParams(
      metricTileQuery(
        readMetricOptions({
          metrics: ["battery_voltage"],
          entity_ids: ["a", "b"],
          aggregate: "max",
        }),
        WINDOW,
      ),
    );
    expect(graph.getAll("entity_id")).toEqual(["a", "b"]);
    expect(graph.getAll("agg")).toEqual(["max"]);
    expect(graph.get("bucket")).toBeNull();
    const table = new URLSearchParams(
      metricTileQuery(
        readMetricOptions({
          metrics: ["battery_voltage"],
          group_by: "device",
          device_ids: ["d"],
          entity_ids: ["a"],
          display: "table",
        }),
        WINDOW,
      ),
    );
    expect(table.get("bucket")).toBe("all");
    expect(table.getAll("agg")).toEqual([
      "last",
      "last_at",
      "mean",
      "min",
      "max",
    ]);
    // a tile per device names devices alone
    expect(table.getAll("device_id")).toEqual(["d"]);
    expect(table.getAll("entity_id")).toEqual([]);
    const number = new URLSearchParams(
      metricTileQuery(
        readMetricOptions({ metrics: ["speed"], display: "number" }),
        WINDOW,
      ),
    );
    expect(number.getAll("agg")).toEqual(["last", "last_at"]);
  });

  it("reads a speed in km/h and leaves a moment and a count alone", () => {
    const response = {
      series: [
        {
          metric_key: "speed",
          unit: "m/s",
          entity_id: "a",
          device_id: null,
          points: [
            {
              time: WINDOW.from,
              values: {
                last: 10,
                last_at: 1_790_000_000,
                count: 4,
                mean: null,
              },
            },
          ],
        },
        {
          metric_key: "battery_voltage",
          unit: "V",
          entity_id: "a",
          device_id: null,
          points: [{ time: WINDOW.from, values: { last: 3.6 } }],
        },
      ],
    } as unknown as SeriesResponse;
    const read = inReadUnits(response);
    expect(read.series?.[0].unit).toBe("km/h");
    expect(read.series?.[0].points[0].values).toEqual({
      last: 36,
      last_at: 1_790_000_000,
      count: 4,
      mean: null,
    });
    expect(read.series?.[1]).toBe(response.series?.[1]);
  });

  it("lists a row per subject and metric, by name, with the moment of the last value", () => {
    const response = {
      series: [
        {
          metric_key: "temperature",
          unit: "°C",
          entity_id: "z",
          device_id: null,
          points: [{ time: WINDOW.from, values: { last: 21, mean: 20.5 } }],
        },
        {
          metric_key: "battery_voltage",
          unit: "V",
          entity_id: "a",
          device_id: null,
          points: [
            {
              time: WINDOW.from,
              values: {
                last: 3.61,
                last_at: 1_790_000_000,
                mean: 3.6,
                min: 3.5,
                max: 3.7,
              },
            },
          ],
        },
      ],
    } as unknown as SeriesResponse;
    const rows = metricRows(
      response,
      new Map([
        ["a", "Bakkie"],
        ["z", "Rhino 14"],
      ]),
      new Map([["battery_voltage", "Battery voltage"]]),
      ["battery_voltage", "temperature"],
    );
    expect(rows.map((r) => [r.subject, r.metric])).toEqual([
      ["Bakkie", "Battery voltage"],
      ["Rhino 14", "temperature"],
    ]);
    expect(rows[0].lastAt).toBe(new Date(1_790_000_000_000).toISOString());
    expect(rows[1].lastAt).toBeNull();
    expect(rows[1].min).toBeNull();
    expect(metricRows(undefined, new Map(), new Map(), [])).toEqual([]);
  });

  it("writes a value in few characters", () => {
    expect([3, 3.614, 104.26, 0.04567].map(tileNumber)).toEqual([
      "3",
      "3.61",
      "104.3",
      "0.046",
    ]);
    expect(tileNumber(null)).toBe("");
  });
});
