import { describe, expect, it } from "vitest";

import { deviceLevel, orderedSubjects, showFigure } from "./fleet";
import {
  devicePerformanceParameters,
  levelOf,
  readFormState,
  type ResultDocument,
} from "@/lib/analyses";

const document: ResultDocument = {
  version: 1,
  module: "device_performance",
  method_version: "device_performance/1",
  subjects: [
    { id: "good", name: "SP1", kind: "device", tracked: "Rhino 14" },
    { id: "bad", name: "SP2", kind: "device", tracked: null },
    { id: "meh", name: "SP0", kind: "device" },
  ],
  periods: [
    {
      key: "main",
      time_from: "2026-08-01T00:00:00Z",
      time_to: "2026-08-31T00:00:00Z",
    },
  ],
  summary: {
    main: {
      good: { level: "ok", battery_v: 3.912, fix_success: 1 },
      bad: {
        level: "critical",
        battery_v: 3.5,
        fix_success: 0.6,
        ttf_p90_s: 150,
      },
      meh: { level: "warn", battery_v: 3.58 },
    },
    levels: {
      good: { battery_v: "ok" },
      bad: { battery_v: "critical", fix_success: "warn" },
      meh: { battery_v: "warn" },
    },
  },
  tables: [],
  charts: [],
  geometries: {},
  warnings: [],
  provenance: {},
};

describe("the fleet's order and words", () => {
  it("puts the worst device first and reads the levels", () => {
    expect(orderedSubjects(document).map((s) => s.name)).toEqual([
      "SP2",
      "SP0",
      "SP1",
    ]);
    expect(deviceLevel(document, "bad")).toBe("critical");
    expect(levelOf(document, "bad", "fix_success")).toBe("warn");
    expect(levelOf(document, "good", "fix_success")).toBeNull();
  });
  it("shows shares as percentages and long seconds as minutes", () => {
    expect(showFigure(0.6, "fix_success")).toBe("60%");
    expect(showFigure(0.25, "lost_uplinks_share")).toBe("25%");
    expect(showFigure(150, "ttf_p90_s")).toBe("3 min");
    expect(showFigure(20, "ttf_median_s")).toBe("20");
    expect(showFigure(3.912, "battery_v")).toBe("3.91");
    expect(showFigure(null, "battery_v")).toBe("–");
    expect(showFigure("6.2", "firmware")).toBe("6.2");
  });
  it("builds the module's parameters from devices, a type or every device", () => {
    const now = new Date("2026-09-16T10:00:00Z");
    const byIds = devicePerformanceParameters(
      readFormState(new URLSearchParams("device=a&device=b&compare=previous")),
      now,
    );
    expect(byIds?.device_ids).toEqual(["a", "b"]);
    expect(byIds?.comparison).toBeDefined();
    expect(byIds?.max_speed_mps).toBe(15);
    expect(
      devicePerformanceParameters(
        readFormState(new URLSearchParams("device_type=t1")),
        now,
      )?.device_type_id,
    ).toBe("t1");
    expect(
      devicePerformanceParameters(
        readFormState(new URLSearchParams("all_devices=1")),
        now,
      )?.all_devices,
    ).toBe(true);
    expect(
      devicePerformanceParameters(readFormState(new URLSearchParams()), now),
    ).toBeNull();
  });
});
