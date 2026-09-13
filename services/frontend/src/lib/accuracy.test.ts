import { describe, expect, it } from "vitest";

import { ACCURACY_WARN_M, imprecise } from "./accuracy";

describe("imprecise", () => {
  it("warns above the threshold only", () => {
    expect(imprecise(ACCURACY_WARN_M + 1)).toBe(true);
    expect(imprecise(455.05)).toBe(true);
    expect(imprecise(ACCURACY_WARN_M)).toBe(false);
    expect(imprecise(3)).toBe(false);
  });
  it("stays quiet without a radius", () => {
    expect(imprecise(null)).toBe(false);
    expect(imprecise(undefined)).toBe(false);
    expect(imprecise(Number.NaN)).toBe(false);
  });
});
