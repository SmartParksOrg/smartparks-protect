import { describe, expect, it } from "vitest";

import type { Metric } from "@/api/types";
import { decimalsFor, niceStep, trendSpecFor } from "@/lib/trend";

const t = (key: string, options?: Record<string, unknown>) =>
  key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? ""));
const metric = (key: string, unit: string | null, value_type = "numeric"): Metric =>
  ({ key, label: key, unit, value_type, category: "device", description: null, created_at: "" }) as Metric;

describe("niceStep", () => {
  it("cuts a range into two to five round intervals", () => {
    expect(niceStep(3.7, 3.9)).toBe(0.05);
    expect(niceStep(12, 31)).toBe(5);
    expect(niceStep(0, 100)).toBe(20);
    expect(niceStep(0, 1)).toBe(0.2);
  });
  it("gives a flat line a step of one", () => {
    expect(niceStep(25, 25)).toBe(1);
  });
});

describe("decimalsFor", () => {
  it("follows the step", () => {
    expect(decimalsFor(0.05)).toBe(2);
    expect(decimalsFor(0.5)).toBe(1);
    expect(decimalsFor(1)).toBe(0);
    expect(decimalsFor(5)).toBe(0);
  });
});

describe("trendSpecFor", () => {
  it("shapes the battery, the movement and the uptime", () => {
    expect(trendSpecFor("battery_voltage", undefined, t)).toMatchObject({ unit: "V", step: 0.05 });
    expect(trendSpecFor("movement", undefined, t)).toMatchObject({ metric: "activity", floor: 0 });
    expect(trendSpecFor("uptime", undefined, t)).toMatchObject({ unit: "d", scale: 1 / 86_400 });
  });
  it("takes any numeric metric of the registry with its label and unit", () => {
    const spec = trendSpecFor("device_temperature", metric("device_temperature", "°C"), t);
    expect(spec).toMatchObject({ metric: "device_temperature", unit: "°C" });
    expect(spec?.ariaLabel).toBe("device_temperature over the period");
  });
  it("leaves text and unknown values plain", () => {
    expect(trendSpecFor("firmware_version", metric("firmware_version", null, "text"), t)).toBeNull();
    expect(trendSpecFor("unknown_key", undefined, t)).toBeNull();
  });
});
