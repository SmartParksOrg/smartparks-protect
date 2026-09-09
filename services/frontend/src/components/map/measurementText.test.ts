import { describe, expect, it } from "vitest";

import { measurementText } from "@/components/map/measurementText";

describe("measurementText", () => {
  it("reads numbers with their unit, integers without decimals", () => {
    expect(
      measurementText({
        metric_key: "b",
        label: "Battery",
        unit: "V",
        value: 3.8,
      }),
    ).toBe("3.80 V");
    expect(
      measurementText({
        metric_key: "s",
        label: "Satellites",
        unit: null,
        value: 7,
      }),
    ).toBe("7");
  });

  it("reads booleans, text and structured values", () => {
    expect(
      measurementText({
        metric_key: "c",
        label: "Charging",
        unit: null,
        value: true,
      }),
    ).toBe("yes");
    expect(
      measurementText({
        metric_key: "r",
        label: "Reset",
        unit: null,
        value: "watchdog",
      }),
    ).toBe("watchdog");
    expect(
      measurementText({
        metric_key: "j",
        label: "Scan",
        unit: null,
        value: { n: 1 },
      }),
    ).toBe('{"n":1}');
    expect(
      measurementText({
        metric_key: "e",
        label: "Empty",
        unit: "m",
        value: null,
      }),
    ).toBe(" m");
  });
});
