import { describe, expect, it } from "vitest";

import { isUnavailableStatus, reasonOf } from "@/lib/availability";

describe("the server's availability as the answers tell it", () => {
  it("knows the gateway statuses", () => {
    expect([502, 503, 504].every(isUnavailableStatus)).toBe(true);
    expect([200, 401, 404, 500].some(isUnavailableStatus)).toBe(false);
  });
  it("reads an update from a 503 and anything else as unreachable", () => {
    expect(reasonOf(503, { unavailable: true, detail: "Protect is being updated" })).toBe("updating");
    expect(reasonOf(503, "Service Unavailable")).toBe("updating");
    expect(reasonOf(502, null)).toBe("unreachable");
    expect(reasonOf(0, null)).toBe("unreachable");
  });
});
