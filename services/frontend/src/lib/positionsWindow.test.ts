import { describe, expect, it } from "vitest";

import { lastPositionsWindow } from "@/lib/positionsWindow";

const NOW = Date.parse("2026-09-15T12:00:00Z");

describe("lastPositionsWindow", () => {
  it("ends a minute past the last record and starts 30 days before that", () => {
    const w = lastPositionsWindow("2025-09-11T09:30:00Z", NOW);
    expect(w.to).toBe("2025-09-11T09:31:00.000Z");
    expect(w.from).toBe("2025-08-12T09:31:00.000Z");
  });
  it("ends now without an anchor or with one in the future", () => {
    expect(lastPositionsWindow(null, NOW).to).toBe(new Date(NOW).toISOString());
    expect(lastPositionsWindow("2064-12-13T10:43:43Z", NOW).to).toBe(new Date(NOW).toISOString());
    expect(lastPositionsWindow("not a date", NOW).to).toBe(new Date(NOW).toISOString());
  });
});
