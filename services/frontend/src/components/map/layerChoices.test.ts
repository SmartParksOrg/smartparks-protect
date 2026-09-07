import { describe, expect, it } from "vitest";

import type { EntityGroup } from "@/api/types";
import {
  DEFAULT_LAYERS,
  hideAllDevices,
  hideAllEntities,
  isDeviceShown,
  showDevices,
  toggleDevice,
  isVisible,
  onlyGroup,
  showEntity,
  showFeature,
  showGateway,
  toggleEntity,
  toggleGroup,
  UNGROUPED_LAYER,
} from "@/components/map/layerChoices";
import type { EntityFeatureProperties } from "@/components/map/layers";

const group = (id: string, parent_id: string | null = null): EntityGroup => ({
  id,
  project_id: "p",
  parent_id,
  name: id,
  sort_order: 0,
  color: null,
  icon_key: null,
  description: null,
  created_at: "",
  updated_at: "",
  entity_count: 0,
});
const groups = [
  group("north"),
  group("herd", "north"),
  group("family", "herd"),
  group("south"),
];
const feature = (
  entity_id: string,
  group_id: string | null,
): EntityFeatureProperties => ({
  entity_id,
  name: entity_id,
  status: "active",
  entity_type: "animal",
  group: "tracked",
  group_id,
  icon_key: "wildlife.generic",
  device_id: null,
  last_seen_at: null,
  position_time: null,
  active_alert_count: 0,
});
const rhino = feature("rhino", "herd");
const calf = feature("calf", "family");
const ranger = feature("ranger", "north");
const loose = feature("loose", null);

describe("layer choices", () => {
  it("shows everything by default", () => {
    for (const f of [rhino, ranger, loose])
      expect(isVisible(f, DEFAULT_LAYERS, groups)).toBe(true);
  });

  it("hiding a parent hides its subgroups and showing it brings them back", () => {
    const hidden = toggleGroup(DEFAULT_LAYERS, "north", false, groups);
    expect(hidden.hidden_groups.sort()).toEqual(["family", "herd", "north"]);
    expect(isVisible(calf, hidden, groups)).toBe(false);
    expect(isVisible(rhino, hidden, groups)).toBe(false);
    expect(isVisible(loose, hidden, groups)).toBe(true);
    expect(toggleGroup(hidden, "north", true, groups).hidden_groups).toEqual(
      [],
    );
  });

  it("showing a subgroup under a hidden parent shows the parent and hides the siblings", () => {
    const withSibling = [...groups, group("team", "north")];
    const deep = toggleGroup(
      toggleGroup(DEFAULT_LAYERS, "north", false, withSibling),
      "family",
      true,
      withSibling,
    );
    expect(deep.hidden_groups.sort()).toEqual(["team"]);
    expect(isVisible(calf, deep, withSibling)).toBe(true);
    const hidden = toggleGroup(DEFAULT_LAYERS, "north", false, withSibling);
    const shown = toggleGroup(hidden, "herd", true, withSibling);
    expect(shown.hidden_groups.sort()).toEqual(["team"]);
    expect(isVisible(rhino, shown, withSibling)).toBe(true);
    expect(isVisible(ranger, shown, withSibling)).toBe(true);
  });

  it("only this group hides every other layer including the ungrouped one", () => {
    const only = onlyGroup(
      toggleEntity(DEFAULT_LAYERS, "rhino", false),
      "herd",
      groups,
    );
    expect(only.hidden_groups.sort()).toEqual(["south", UNGROUPED_LAYER]);
    expect(isVisible(calf, only, groups)).toBe(true);
    expect(only.hidden_entities).toEqual([]);
    expect(isVisible(rhino, only, groups)).toBe(true);
    expect(isVisible(loose, only, groups)).toBe(false);
    expect(
      onlyGroup(DEFAULT_LAYERS, UNGROUPED_LAYER, groups).hidden_groups.sort(),
    ).toEqual(["family", "herd", "north", "south"]);
  });

  it("hides and shows one entity", () => {
    const hidden = toggleEntity(DEFAULT_LAYERS, "rhino", false);
    expect(isVisible(rhino, hidden, groups)).toBe(false);
    expect(isVisible(rhino, toggleEntity(hidden, "rhino", true), groups)).toBe(
      true,
    );
  });

  it("showing a child under a switched-off parent switches the parent on and hides the rest", () => {
    const off = { ...DEFAULT_LAYERS, gateways: false };
    const one = showGateway(off, "g1", ["g1", "g2", "g3"]);
    expect(one.gateways).toBe(true);
    expect(one.hidden_gateways.sort()).toEqual(["g2", "g3"]);
    const two = showGateway(one, "g2", ["g1", "g2", "g3"]);
    expect(two.hidden_gateways).toEqual(["g3"]);
    const feature = showFeature(
      { ...DEFAULT_LAYERS, features: false },
      { id: "f1", feature_type: "zone" },
      ["f1", "f2"],
      ["zone", "site"],
    );
    expect(feature.features).toBe(true);
    expect(feature.hidden_feature_types).toEqual(["site"]);
    expect(feature.hidden_features).toEqual(["f2"]);
  });

  it("showing one entity after hide all shows its group chain and keeps the others hidden", () => {
    const none = hideAllEntities(DEFAULT_LAYERS, groups);
    expect(isVisible(rhino, none, groups)).toBe(false);
    const one = showEntity(none, rhino, groups, ["calf-in-herd"]);
    expect(isVisible(rhino, one, groups)).toBe(true);
    expect(one.hidden_entities).toEqual(["calf-in-herd"]);
    expect(isVisible(loose, one, groups)).toBe(false);
  });
});

describe("device layer choices", () => {
  it("shows no device until someone switches it on", () => {
    expect(isDeviceShown("d1", DEFAULT_LAYERS)).toBe(false);
    const on = toggleDevice(DEFAULT_LAYERS, "d1", true);
    expect(isDeviceShown("d1", on)).toBe(true);
    expect(isDeviceShown("d2", on)).toBe(false); // a device that arrives later stays off
    expect(isDeviceShown("d1", toggleDevice(on, "d1", false))).toBe(false);
  });

  it("shows all listed devices and hides them all again", () => {
    const all = showDevices(toggleDevice(DEFAULT_LAYERS, "d1", true), ["d1", "d2"]);
    expect(all.shown_devices).toEqual(["d1", "d2"]);
    expect(hideAllDevices(all).shown_devices).toEqual([]);
  });
});
