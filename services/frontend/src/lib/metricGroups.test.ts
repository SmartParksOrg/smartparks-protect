import { describe, expect, it } from "vitest";

import { groupMetrics } from "./metricGroups";

describe("groupMetrics", () => {
  it("groups by category in the reader's order and sorts each group by label", () => {
    const categories: Record<string, string> = {
      heart_rate: "physiology",
      battery_voltage: "device_health",
      activity: "movement",
      cmdq_temperature: "physiology",
      odd: "something_new",
    };
    const items = [
      { metric_key: "battery_voltage", label: "Battery" },
      { metric_key: "odd", label: "Odd" },
      { metric_key: "unknown", label: "Unknown" },
      { metric_key: "heart_rate", label: "Heart rate" },
      { metric_key: "cmdq_temperature", label: "Body temperature" },
      { metric_key: "activity", label: "Activity" },
    ];
    const groups = groupMetrics(items, (key) => categories[key]);
    expect(groups.map(([category]) => category)).toEqual([
      "physiology",
      "movement",
      "device_health",
      "something_new",
      "uncategorized",
    ]);
    expect(groups[0][1].map((m) => m.label)).toEqual([
      "Body temperature",
      "Heart rate",
    ]);
    expect(groups[4][1].map((m) => m.metric_key)).toEqual(["unknown"]);
  });
});
