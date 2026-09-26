import { describe, expect, it } from "vitest";

import { compassPoint, courseText, kmh, speedText } from "@/lib/speed";

describe("speed", () => {
  it("reads metres per second as whole km/h", () => {
    expect(kmh(12)).toBeCloseTo(43.2);
    expect(speedText(12)).toBe("43 km/h");
    expect(speedText(0)).toBe("0 km/h");
  });

  it("names the nearest compass point, wrapping at north", () => {
    expect(compassPoint(0)).toBe("N");
    expect(compassPoint(52.5)).toBe("NE");
    expect(compassPoint(350)).toBe("N");
    expect(compassPoint(-90)).toBe("W");
    expect(compassPoint(210)).toBe("SW");
  });

  it("gives a course only while moving", () => {
    expect(courseText(52.5, 12)).toBe("NE 53°");
    expect(courseText(52.5, 0)).toBe("");
    expect(courseText(null, 12)).toBe("");
    expect(courseText(52.5, null)).toBe("");
  });
});
