import { describe, expect, it } from "vitest";

import {
  allTimezones,
  isTimezone,
  orderedTimezones,
  zoneLabel,
  zoneOffset,
} from "./timezones";

describe("timezones", () => {
  it("knows the real zones and refuses a typo or an abbreviation", () => {
    expect(isTimezone("Africa/Windhoek")).toBe(true);
    expect(isTimezone("UTC")).toBe(true);
    expect(isTimezone("Africa/Windhoek ")).toBe(false);
    expect(isTimezone("CAT")).toBe(false);
    expect(isTimezone("")).toBe(false);
  });

  it("labels a zone with its offset", () => {
    // Windhoek keeps UTC+2 all year since 2017; Amsterdam is +1 in January
    expect(
      zoneOffset("Africa/Windhoek", new Date("2026-01-15T12:00:00Z")),
    ).toBe("UTC+02:00");
    expect(
      zoneLabel("Europe/Amsterdam", new Date("2026-01-15T12:00:00Z")),
    ).toBe("Europe/Amsterdam (UTC+01:00)");
    expect(zoneOffset("UTC")).toBe("UTC+00:00");
    expect(zoneLabel("Not/AZone")).toBe("Not/AZone");
  });

  it("offers every zone, the ones worth a first look at the top", () => {
    const all = allTimezones();
    expect(all.length).toBeGreaterThan(300);
    expect(all).toContain("UTC");
    const ordered = orderedTimezones(
      ["Africa/Windhoek", "Africa/Nairobi"],
      "Europe/Oddity",
    );
    expect(ordered.slice(1, 3)).toEqual(["Africa/Windhoek", "Africa/Nairobi"]);
    expect(ordered[3]).toBe("Europe/Oddity"); // the stored value stays choosable
    expect(new Set(ordered).size).toBe(ordered.length);
    const rest = ordered.slice(4);
    expect(rest).toEqual([...rest].sort((a, b) => a.localeCompare(b)));
  });
});
