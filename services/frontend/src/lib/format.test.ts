import { describe, expect, it } from "vitest";

import { formatTime, formatTimeShort } from "@/lib/format";

describe("formatTimeShort", () => {
  const now = new Date(2026, 8, 7, 12, 0, 0);

  it("shows the time alone for today", () => {
    const today = new Date(2026, 8, 7, 9, 44, 14).toISOString();
    const text = formatTimeShort(today, now);
    expect(text).toMatch(/9:44:14/);
    expect(text).not.toMatch(/Sep|2026/);
  });

  it("shows a short date with the time for other days", () => {
    const earlier = new Date(2026, 8, 6, 21, 5, 0).toISOString();
    const text = formatTimeShort(earlier, now);
    expect(text).toMatch(/Sep/);
    expect(text).not.toMatch(/2026/);
  });

  it("is empty without a value", () => {
    expect(formatTimeShort(null, now)).toBe("");
  });
});

import { formatDuration, formatMeasurement } from "./format";

describe("durations", () => {
  it("spells seconds out as days, hours, minutes", () => {
    expect(formatDuration(432_000)).toBe("5 d 0 h");
    expect(formatDuration(11_400)).toBe("3 h 10 min");
    expect(formatDuration(600)).toBe("10 min");
    expect(formatDuration(42)).toBe("42 s");
  });
  it("formats a measurement with its unit and a seconds metric as a duration", () => {
    expect(formatMeasurement(432_000, "s")).toBe("5 d 0 h");
    expect(formatMeasurement(3.6, "V")).toBe("3.60 V");
    expect(formatMeasurement(123.456, "m")).toBe("123.5 m");
    expect(formatMeasurement(null, "s")).toBe("");
  });
});

describe("the 24 hour clock", () => {
  // Tim, 2026-09-18: an English browser is usually en-US, which writes "7:05:00 PM" on the live
  // map's Position row. A field team reads 19:05.
  const evening = "2026-09-18T19:05:00Z";
  it("never writes AM or PM, whatever the browser's locale", () => {
    expect(formatTime(evening)).not.toMatch(/[AP]M/i);
    expect(formatTimeShort(evening, new Date("2026-09-20T12:00:00Z"))).not.toMatch(
      /[AP]M/i,
    );
  });

  it("writes the evening hour as 19 or later, not as 7", () => {
    // whatever zone the test machine is in, an evening in UTC is never hour 7 on a 24 hour clock
    expect(formatTime(evening)).toMatch(/\b(1[0-9]|2[0-3]|0[0-9]):05:00\b/);
  });
});
