import { describe, expect, it } from "vitest";

import {
  isDeviceFix,
  positionKindExplanation,
  positionKindLabel,
} from "@/lib/positionKind";

const t = (k: string) => k;

describe("what a position actually is", () => {
  it("says nothing about a device's own fix, which is what a reader assumes", () => {
    for (const kind of [null, undefined, "device", "gnss"]) {
      expect(isDeviceFix(kind)).toBe(true);
      expect(positionKindLabel(kind, t)).toBeNull();
    }
  });

  it.each([
    ["network", "network estimate", "estimate"],
    ["static", "fixed place", "fixed"],
    ["proximity", "heard by a reader", "heard"],
  ])("labels %s, long and short", (kind, long, short) => {
    expect(isDeviceFix(kind)).toBe(false);
    expect(positionKindLabel(kind, t)).toBe(long);
    expect(positionKindLabel(kind, t, true)).toBe(short);
    expect(positionKindExplanation(kind, t)).toBeTruthy();
  });

  it("every kind that is not a fix can be explained, or the label is a riddle", () => {
    for (const kind of ["network", "static", "proximity"]) {
      const text = positionKindExplanation(kind, t) ?? "";
      expect(text.length).toBeGreaterThan(30);
    }
  });
});
