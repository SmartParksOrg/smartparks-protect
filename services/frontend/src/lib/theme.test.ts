import { describe, expect, it } from "vitest";

import { isTheme, nextTheme, resolveTheme } from "@/lib/theme";

describe("theme", () => {
  it("resolves system against the device", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
  });
  it("cycles light, dark, system", () => {
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
    expect(nextTheme("system")).toBe("light");
  });
  it("accepts the three names only", () => {
    expect(isTheme("dark")).toBe(true);
    expect(isTheme("night")).toBe(false);
    expect(isTheme(null)).toBe(false);
  });
});
