import { describe, expect, it } from "vitest";

import { lastMovement, movementLevel, stillHours } from "./movement";

describe("movement", () => {
  const now = Date.parse("2026-09-14T12:00:00Z");
  it("levels the time since the last movement", () => {
    expect(movementLevel(null, now)).toBeNull();
    expect(movementLevel("2026-09-14T10:00:00Z", now)).toBe("ok");
    expect(movementLevel("2026-09-13T23:00:00Z", now)).toBe("warn");
    expect(movementLevel("2026-09-13T11:00:00Z", now)).toBe("critical");
  });
  it("takes the newer of the accelerometer and the fixes and names it", () => {
    expect(lastMovement(null, null)).toEqual({ at: null, source: null });
    expect(lastMovement("2026-09-14T10:00:00Z", null)).toEqual({ at: "2026-09-14T10:00:00Z", source: "accelerometer" });
    expect(lastMovement(null, "2026-09-14T10:00:00Z")).toEqual({ at: "2026-09-14T10:00:00Z", source: "positions" });
    expect(lastMovement("2026-09-13T10:00:00Z", "2026-09-14T10:00:00Z")).toEqual({ at: "2026-09-14T10:00:00Z", source: "positions" });
    expect(lastMovement("2026-09-14T11:00:00Z", "2026-09-14T10:00:00Z")).toEqual({ at: "2026-09-14T11:00:00Z", source: "accelerometer" });
  });
  it("counts the still hours only once it is worth a word", () => {
    expect(stillHours("2026-09-14T10:00:00Z", now)).toBeNull();
    expect(stillHours("2026-09-13T21:30:00Z", now)).toBe(14);
    expect(stillHours(undefined, now)).toBeNull();
  });
});
