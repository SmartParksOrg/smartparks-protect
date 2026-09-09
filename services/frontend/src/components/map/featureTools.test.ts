import { describe, expect, it } from "vitest";

import {
  featureTypesFor,
  ruleTemplateFor,
} from "@/components/map/featureTools";

describe("feature tools", () => {
  it("offers the types a drawing can become", () => {
    expect(featureTypesFor({ type: "Point", coordinates: [0, 0] })).toEqual([
      "site",
    ]);
    expect(featureTypesFor({ type: "LineString", coordinates: [] })).toEqual([
      "route",
    ]);
    expect(featureTypesFor({ type: "Polygon", coordinates: [] })).toEqual([
      "geofence",
      "zone",
    ]);
    expect(featureTypesFor(null)).toEqual(["geofence", "zone"]);
  });

  it("starts the rule that fits the feature", () => {
    expect(ruleTemplateFor("geofence")).toBe("geofence_exit");
    expect(ruleTemplateFor("site")).toBe("near_site");
    expect(ruleTemplateFor("zone")).toBe("near_site");
    expect(ruleTemplateFor("route")).toBeNull();
  });
});
