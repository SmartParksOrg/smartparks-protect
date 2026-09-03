import { describe, expect, it } from "vitest";

import type { SeriesResponse } from "@/api/types";
import { bucketLabel, histogram, rangeFor, toLongRows } from "@/lib/analytics";

describe("analytics helpers", () => {
  it("anchors a range at the minute so the query key stays stable", () => {
    const range = rangeFor("24h", new Date("2026-04-01T10:30:45.678Z"));
    expect(range.to).toBe("2026-04-01T10:30:00.000Z");
    expect(range.from).toBe("2026-03-31T10:30:00.000Z");
  });

  it("flattens series into time ordered rows with owner names", () => {
    const response = {
      series: [
        { metric_key: "battery_voltage", unit: "V", entity_id: "e1", device_id: null, points: [{ time: "2026-04-01T02:00:00Z", values: { mean: 3.6 } }, { time: "2026-04-01T01:00:00Z", values: { mean: 3.5 } }] },
      ],
    } as unknown as SeriesResponse;
    const rows = toLongRows(response, new Map([["e1", "Rhino 14"]]));
    expect(rows.map((r) => r.time)).toEqual(["2026-04-01T01:00:00Z", "2026-04-01T02:00:00Z"]);
    expect(rows[0].owner_name).toBe("Rhino 14");
  });

  it("bins values into a histogram and labels bucket widths", () => {
    const { edges, counts } = histogram([1, 2, 2, 3, 10], 3);
    expect(edges).toHaveLength(3);
    expect(counts.reduce((a, b) => a + b, 0)).toBe(5);
    expect(counts[2]).toBe(1);
    expect(bucketLabel(3600)).toBe("1 h");
    expect(bucketLabel(900)).toBe("15 min");
    expect(bucketLabel(86400 * 7)).toBe("7 d");
  });
});
