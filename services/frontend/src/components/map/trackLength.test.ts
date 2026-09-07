import { describe, expect, it } from "vitest";

import {
  clampHours,
  describeHours,
  parseTrackLength,
  trackFrom,
  trackLengthParam,
} from "@/components/map/trackLength";

describe("track length", () => {
  it("parses the URL value with the fallback for nothing or nonsense", () => {
    expect(parseTrackLength(null, 24)).toBe(24);
    expect(parseTrackLength("", "assigned")).toBe("assigned");
    expect(parseTrackLength("168", 24)).toBe(168);
    expect(parseTrackLength("assigned", 24)).toBe("assigned");
    expect(parseTrackLength("abc", 48)).toBe(48);
    expect(parseTrackLength("-5", 48)).toBe(48);
  });

  it("keeps hours between one hour and ninety days", () => {
    expect(clampHours(0)).toBe(1);
    expect(clampHours(5000)).toBe(90 * 24);
    expect(clampHours(36.4)).toBe(36);
    expect(clampHours(Number.NaN)).toBe(24);
  });

  it("says days for whole days and hours otherwise", () => {
    expect(describeHours(6)).toEqual({ value: 6, unit: "hours" });
    expect(describeHours(24)).toEqual({ value: 1, unit: "days" });
    expect(describeHours(36)).toEqual({ value: 36, unit: "hours" });
    expect(describeHours(21 * 24)).toEqual({ value: 21, unit: "days" });
  });

  it("writes the URL value back", () => {
    expect(trackLengthParam(48)).toBe("48");
    expect(trackLengthParam("assigned")).toBe("assigned");
  });

  it("starts a track at the assignment or the given hours before now", () => {
    const now = Date.parse("2026-09-07T12:00:00Z");
    expect(trackFrom(24, "2026-01-01T00:00:00+00:00", 24, now)).toBe("2026-09-06T12:00:00.000Z");
    expect(trackFrom("assigned", "2026-01-01T00:00:00+00:00", 24, now)).toBe(
      "2026-01-01T00:00:00+00:00",
    );
    // no assignment: the fallback hours, so the entity still gets a track
    expect(trackFrom("assigned", null, 6, now)).toBe("2026-09-07T06:00:00.000Z");
  });
});
