import { describe, expect, it } from "vitest";

import type { RecordRow } from "@/api/types";
import {
  inputValue,
  recordsHref,
  cellOf,
  columnsOf,
  readRecordsState,
  seriesOf,
  windowFor,
  writeRecordsState,
} from "@/lib/records";

const row = (
  time: string,
  measurements: RecordRow["measurements"],
  state: RecordRow["state"] = null,
  speed: number | null = null,
): RecordRow => ({
  time,
  device_id: "d",
  device_name: "SP05",
  entity_id: "e",
  entity_name: "Rhino 14",
  project_id: "p",
  position:
    speed == null
      ? null
      : {
          id: 1,
          lat: -24.9,
          lon: 31.5,
          altitude_m: 12,
          speed_mps: speed,
          heading_deg: null,
          accuracy_m: 4,
          satellites: 9,
          valid: true,
          curated_fields: [],
          source_event_id: 1,
          source_event_ingested_at: null,
          trace_id: null,
        },
  measurements,
  state,
  source_event_id: 1,
  source_event_ingested_at: null,
  trace_id: null,
});

describe("records state", () => {
  it("round-trips through the URL with the mode", () => {
    const params = new URLSearchParams(
      "entity=e1&entity=e2&device=d1&range=custom&from=2026-04-01T00:00&to=2026-04-02T00:00&tz=UTC",
    );
    const state = readRecordsState(params);
    expect(state).toEqual({
      entities: ["e1", "e2"],
      devices: ["d1"],
      range: "custom",
      from: "2026-04-01T00:00",
      to: "2026-04-02T00:00",
      timezone: "UTC",
      at: null,
    });
    expect(writeRecordsState(state).toString()).toBe(
      "mode=table&entity=e1&entity=e2&device=d1&range=custom&from=2026-04-01T00%3A00&to=2026-04-02T00%3A00&tz=UTC",
    );
    expect(readRecordsState(new URLSearchParams("range=nonsense")).range).toBe(
      "7d",
    );
  });

  it("makes the window from the preset, the custom range or the assignment", () => {
    const now = new Date("2026-04-10T00:00:00Z");
    const base = {
      entities: [],
      devices: [],
      from: null,
      to: null,
      timezone: "UTC",
    };
    expect(windowFor({ ...base, range: "24h" }, null, now)).toEqual({
      from: "2026-04-09T00:00:00.000Z",
      to: "2026-04-10T00:00:00.000Z",
    });
    expect(
      windowFor(
        {
          ...base,
          range: "custom",
          from: "2026-04-01T00:00",
          to: "2026-04-02T00:00",
        },
        null,
        now,
      ).from,
    ).toMatch(/^2026-0[34]-\d\dT/);
    expect(
      windowFor({ ...base, range: "assignment" }, "2026-03-01T00:00:00Z", now),
    ).toEqual({ from: "2026-03-01T00:00:00Z", to: "2026-04-10T00:00:00.000Z" });
    expect(windowFor({ ...base, range: "assignment" }, null, now).from).toBe(
      "2026-03-11T00:00:00.000Z",
    );
  });
});

describe("records columns", () => {
  const labels = new Map([
    ["battery_voltage", { label: "Battery voltage", unit: "V" }],
  ]);
  const rows = [
    row(
      "2026-04-01T12:05:00Z",
      { temperature: 21.5, reset_reason: "watchdog" },
      { firmware: "7.2.0" },
    ),
    row("2026-04-01T12:00:00Z", { battery_voltage: 3.8 }, null, 1.5),
  ];

  it("lists the fixed columns, then the metrics seen, then the state fields", () => {
    const columns = columnsOf(rows, labels);
    expect(columns.map((c) => c.key)).toEqual([
      "time",
      "entity",
      "device",
      "lat",
      "lon",
      "accuracy_m",
      "speed_kmh",
      "altitude_m",
      "m:temperature",
      "m:reset_reason",
      "m:battery_voltage",
      "s:firmware",
    ]);
    expect(columns.find((c) => c.key === "m:battery_voltage")).toMatchObject({
      label: "Battery voltage",
      unit: "V",
      numeric: true,
    });
    expect(columns.find((c) => c.key === "m:reset_reason")?.numeric).toBe(
      false,
    );
  });

  it("reads cells and makes series oldest first", () => {
    const columns = columnsOf(rows, labels);
    const speed = columns.find((c) => c.key === "speed_kmh")!;
    expect(cellOf(rows[1], speed)).toBeCloseTo(5.4);
    expect(cellOf(rows[0], speed)).toBeNull();
    expect(
      cellOf(
        rows[0],
        columns.find((c) => c.key === "s:firmware")!,
      ),
    ).toBe("7.2.0");
    const battery = columns.find((c) => c.key === "m:battery_voltage")!;
    expect(seriesOf(rows, battery)).toEqual([
      { time: "2026-04-01T12:00:00Z", value: 3.8 },
    ]);
  });
});

describe("records links", () => {
  it("lands on the twelve hours around a moment with the row marked", () => {
    const href = recordsHref("p1", {
      devices: ["d1"],
      at: "2026-09-04T12:00:00.000Z",
    });
    const params = new URLSearchParams(href.split("?")[1]);
    expect(href.startsWith("/projects/p1/analyze/explorer?")).toBe(true);
    expect(params.get("mode")).toBe("table");
    expect(params.getAll("device")).toEqual(["d1"]);
    expect(params.get("range")).toBe("custom");
    expect(params.get("from")).toBe("2026-09-04T00:00:00.000Z");
    expect(params.get("to")).toBe("2026-09-05T00:00:00.000Z");
    expect(params.get("at")).toBe("2026-09-04T12:00:00.000Z");
  });
  it("takes the last 30 days without a moment, and ignores a bad one", () => {
    const params = new URLSearchParams(
      recordsHref("p1", { entities: ["e1"], at: "yesterday" }).split("?")[1],
    );
    expect(params.get("range")).toBe("30d");
    expect(params.get("at")).toBeNull();
    expect(params.getAll("entity")).toEqual(["e1"]);
  });
});

describe("records inputs", () => {
  it("shows an input's own value and a zoned time as a local minute", () => {
    expect(inputValue(null)).toBe("");
    expect(inputValue("2026-04-01T00:00")).toBe("2026-04-01T00:00");
    expect(inputValue("2026-04-01T00:00:00.000Z")).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/,
    );
    expect(inputValue("xZ")).toBe("");
  });
});
