import { describe, expect, it } from "vitest";

import { pictureVersion } from "@/lib/pictureVersion";

describe("pictureVersion", () => {
  it("gives the same version for both notations of one instant", () => {
    expect(pictureVersion("2026-09-07T12:22:21.993690Z")).toBe(pictureVersion("2026-09-07T12:22:21.993690+00:00"));
    expect(pictureVersion("2026-09-07T12:22:21.993690Z")).toBe("2026-09-07T12:22:21.993Z");
  });

  it("keeps an unparsable string and drops an empty one", () => {
    expect(pictureVersion("v3")).toBe("v3");
    expect(pictureVersion(null)).toBeNull();
    expect(pictureVersion(undefined)).toBeNull();
  });
});
