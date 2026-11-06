import { describe, expect, it } from "vitest";

import { coverageBbox } from "@/lib/bbox";

describe("coverageBbox", () => {
  it("pads the view by a quarter on each side and snaps outward", () => {
    // a view 4 wide and 4 high: the step is 1, the box grows to 6 by 6
    expect(coverageBbox(16, -22, 20, -18)).toBe("15.00000,-23.00000,21.00000,-17.00000");
  });

  it("keeps the same box for a pan smaller than the step", () => {
    const first = coverageBbox(16.1, -21.9, 20.1, -17.9);
    const panned = coverageBbox(16.3, -21.8, 20.3, -17.8);
    expect(panned).toBe(first);
    // a pan of a whole step moves the box
    expect(coverageBbox(17.2, -21.9, 21.2, -17.9)).not.toBe(first);
  });

  it("stays inside the world", () => {
    expect(coverageBbox(-179, -89, 179, 89)).toBe("-180.00000,-90.00000,180.00000,90.00000");
  });
});
