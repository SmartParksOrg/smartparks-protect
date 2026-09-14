import { describe, expect, it } from "vitest";

import { movementLevel, stillHours } from "./movement";

describe("movement", () => {
  const now = Date.parse("2026-09-14T12:00:00Z");
  it("levels the time since the last movement", () => {
    expect(movementLevel(null, now)).toBeNull();
    expect(movementLevel("2026-09-14T10:00:00Z", now)).toBe("ok");
    expect(movementLevel("2026-09-13T23:00:00Z", now)).toBe("warn");
    expect(movementLevel("2026-09-13T11:00:00Z", now)).toBe("critical");
  });
  it("counts the still hours only once it is worth a word", () => {
    expect(stillHours("2026-09-14T10:00:00Z", now)).toBeNull();
    expect(stillHours("2026-09-13T21:30:00Z", now)).toBe(14);
    expect(stillHours(undefined, now)).toBeNull();
  });
});
