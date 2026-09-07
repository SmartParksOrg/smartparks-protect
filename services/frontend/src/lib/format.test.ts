import { describe, expect, it } from "vitest";

import { formatTimeShort } from "@/lib/format";

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
