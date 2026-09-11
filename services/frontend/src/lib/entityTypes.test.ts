import { describe, expect, it } from "vitest";

import { hiddenTypeIds, splitSelection, subtypesOf, topLevel, typePath, visibleTypes } from "@/lib/entityTypes";

const types = [
  { id: "w", label: "Wildlife", icon_key: "wildlife.generic", parent_id: null },
  { id: "e", label: "Elephant", icon_key: "wildlife.elephant", parent_id: "w" },
  { id: "a", label: "Aardvark", icon_key: "wildlife.aardvark", parent_id: "w" },
  { id: "v", label: "Vehicles", icon_key: "vehicle.4x4", parent_id: null },
  { id: "c", label: "Car", icon_key: "vehicle.car", parent_id: "v" },
  { id: "animal", label: "Animal", icon_key: "wildlife.rhino" },
];

describe("entity types", () => {
  it("lists types and sub-types by label", () => {
    expect(topLevel(types).map((t) => t.id)).toEqual(["animal", "v", "w"]);
    expect(subtypesOf(types, "w").map((t) => t.label)).toEqual(["Aardvark", "Elephant"]);
  });

  it("hides a type with its sub-types", () => {
    const hidden = hiddenTypeIds({ hidden_entity_type_ids: ["v", "a", 3] });
    expect(visibleTypes(types, hidden).map((t) => t.id)).toEqual(["w", "e", "animal"]);
    expect(hiddenTypeIds(undefined).size).toBe(0);
  });

  it("splits a chosen row into type and sub-type", () => {
    expect(splitSelection(types, "e")).toEqual({ typeId: "w", subtypeId: "e" });
    expect(splitSelection(types, "animal")).toEqual({ typeId: "animal", subtypeId: "" });
    expect(splitSelection(types, "missing")).toEqual({ typeId: "", subtypeId: "" });
  });

  it("names the path", () => {
    expect(typePath(types, "e")).toBe("Wildlife · Elephant");
    expect(typePath(types, "animal")).toBe("Animal");
    expect(typePath(types, null)).toBe("");
  });
});
