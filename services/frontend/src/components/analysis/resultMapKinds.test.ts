import { describe, expect, it } from "vitest";

import { ANALYSIS_KINDS } from "@/components/map/analysisLayers";

/** Which result geometries a run's map offers.
 *
 * The map used to take a fixed list of kinds and keep the ones the run had, so a module that
 * emitted a kind the list had never heard of drew nothing and offered no chip — `contact` did
 * exactly that, and it took looking at the page to notice. The rule is the other way round now:
 * the run says which kinds it has, and the fixed list only decides the order.
 */
function available(geometries: Record<string, number>): string[] {
  return [
    ...ANALYSIS_KINDS.filter((k) => geometries[k]),
    ...Object.keys(geometries).filter(
      (k) =>
        geometries[k] && !(ANALYSIS_KINDS as readonly string[]).includes(k),
    ),
  ];
}

describe("the kinds a result map offers", () => {
  it("keeps the known kinds in their drawing order", () => {
    expect(available({ kde: 2, area: 1, mcp: 1 })).toEqual([
      "area",
      "mcp",
      "kde",
    ]);
  });

  it("offers a kind the list has never heard of", () => {
    expect(available({ contact: 4 })).toEqual(["contact"]);
  });

  it("puts an unknown kind after the known ones", () => {
    expect(available({ contact: 4, area: 1 })).toEqual(["area", "contact"]);
  });

  it("leaves out a kind the run produced none of", () => {
    expect(available({ contact: 0, area: 2 })).toEqual(["area"]);
  });
});
