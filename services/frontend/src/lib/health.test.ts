import { describe, expect, it } from "vitest";

import { dotLevel } from "@/lib/health";

const ok = { level: "ok", reasons: [], checked_at: "2026-09-12T12:00:00Z" };
const degraded = {
  level: "degraded",
  reasons: ["the rules worker has not reported for over 15 minutes"],
  checked_at: "2026-09-12T12:00:00Z",
};

describe("dotLevel", () => {
  it("follows the server's summary while it answers", () => {
    expect(dotLevel(ok, 0)).toBe("ok");
    expect(dotLevel(degraded, 0)).toBe("degraded");
    expect(dotLevel(undefined, 0)).toBe("unknown");
  });
  it("turns red only after two failed polls in a row", () => {
    expect(dotLevel(ok, 1)).toBe("ok");
    expect(dotLevel(degraded, 1)).toBe("degraded");
    expect(dotLevel(undefined, 1)).toBe("ok");
    expect(dotLevel(ok, 2)).toBe("down");
    expect(dotLevel(undefined, 3)).toBe("down");
  });
});
