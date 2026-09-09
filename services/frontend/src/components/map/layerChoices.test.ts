import { describe, expect, it } from "vitest";

import type { EntityGroup } from "@/api/types";
import {
  DEFAULT_LAYERS,
  hideAllDevices,
  hideDevices,
  hideAllEntities,
  isDeviceShown,
  isGroupShown,
  isVisible,
  onlyGroup,
  projectLayerOf,
  showDevices,
  showEntity,
  showFeature,
  showGateway,
  toggleDevice,
  toggleEntity,
  toggleGroup,
  UNGROUPED_LAYER,
  ungroupedLayerOf,
  withProjectShown,
  hideAllEvents,
  hideAllFeatures,
  hideAllGateways,
  showAllEvents,
  showAllFeatures,
  showAllGateways,
  revealEntity,
  revealDevice,
  revealGateway,
  revealFeature,
  isOnlyGateway,
  toggleOnlyGateway,
  coverageGatewayIds,
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
    const all = showDevices(toggleDevice(DEFAULT_LAYERS, "d1", true), [
      "d1",
      "d2",
    ]);
    expect(all.shown_devices).toEqual(["d1", "d2"]);
    expect(hideAllDevices(all).shown_devices).toEqual([]);
    expect(hideDevices(all, ["d1"]).shown_devices).toEqual(["d2"]); // a project's devices off, the rest stay
  });
});

describe("show all and hide all on the features, events and coverage tabs", () => {
  it("clears the hidden lists and switches the layer on, or switches it off", () => {
    const some = {
      ...DEFAULT_LAYERS,
      features: false,
      hidden_feature_types: ["fence"],
      hidden_features: ["f1"],
      hidden_event_types: ["alarm"],
      gateways: false,
      hidden_gateways: ["g1"],
    };
    const features = showAllFeatures(some);
    expect([
      features.features,
      features.hidden_feature_types,
      features.hidden_features,
    ]).toEqual([true, [], []]);
    expect(hideAllFeatures(features).features).toBe(false);
    const events = showAllEvents(some);
    expect([events.events, events.hidden_event_types]).toEqual([true, []]);
    expect(hideAllEvents(events).events).toBe(false);
    const gateways = showAllGateways(some);
    expect([gateways.gateways, gateways.hidden_gateways]).toEqual([true, []]);
    expect(hideAllGateways(gateways).gateways).toBe(false);
  });

  it("ticking one gateway after hide all shows only that one", () => {
    const one = showGateway(hideAllGateways(DEFAULT_LAYERS), "g1", [
      "g1",
      "g2",
      "g3",
    ]);
    expect(one.gateways).toBe(true);
    expect(one.hidden_gateways.sort()).toEqual(["g2", "g3"]);
  });
});

describe("the project as a layer (all-projects scope)", () => {
  const groups = [group("g1"), group("g2")].map((g, i) => ({
    ...g,
    project_id: i === 0 ? "p1" : "p2",
  }));
  const entity = (id: string, project_id: string, group_id: string | null) =>
    ({
      entity_id: id,
      project_id,
      group_id,
      name: id,
    }) as unknown as Parameters<typeof isVisible>[0];

  it("hides every group and the ungrouped layer of a hidden project", () => {
    const hidden = toggleGroup(
      DEFAULT_LAYERS,
      projectLayerOf("p1"),
      false,
      groups,
    );
    expect(isGroupShown("g1", hidden, groups)).toBe(false);
    expect(isGroupShown(ungroupedLayerOf("p1"), hidden, groups)).toBe(false);
    expect(isGroupShown("g2", hidden, groups)).toBe(true);
    expect(isVisible(entity("e1", "p1", null), hidden, groups, true)).toBe(
      false,
    );
    expect(isVisible(entity("e2", "p2", null), hidden, groups, true)).toBe(
      true,
    );
  });

  it("showing a group inside a hidden project shows the project again", () => {
    const hidden = toggleGroup(
      DEFAULT_LAYERS,
      projectLayerOf("p1"),
      false,
      groups,
    );
    const shown = withProjectShown(
      toggleGroup(hidden, "g1", true, groups),
      "g1",
      groups,
    );
    expect(isGroupShown("g1", shown, groups)).toBe(true);
  });

  it("keeps the shared ungrouped layer within one project", () => {
    expect(isVisible(entity("e1", "p1", null), DEFAULT_LAYERS, groups)).toBe(
      true,
    );
  });
});

describe("hide all in the all scope", () => {
  it("hides every project, group and ungrouped layer", () => {
    const groups = [{ ...group("g1"), project_id: "p1" }];
    const hidden = hideAllEntities(DEFAULT_LAYERS, groups, ["p1", "p2"]);
    const entity = (id: string, project_id: string, group_id: string | null) =>
      ({
        entity_id: id,
        project_id,
        group_id,
        name: id,
      }) as unknown as Parameters<typeof isVisible>[0];
    expect(isVisible(entity("e1", "p1", "g1"), hidden, groups, true)).toBe(
      false,
    );
    expect(isVisible(entity("e2", "p1", null), hidden, groups, true)).toBe(
      false,
    );
    expect(isVisible(entity("e3", "p2", null), hidden, groups, true)).toBe(
      false,
    );
  });
});

describe("a show-on-map link reveals the object (phase 19)", () => {
  const groups = [group("region"), group("herd", "region")];
  const props = (
    entity_id: string,
    group_id: string | null,
    project_id = "p",
  ) =>
    ({ entity_id, group_id, project_id }) as unknown as EntityFeatureProperties;

  it("shows a hidden entity and the group chain above it without touching the rest", () => {
    const hidden = {
      ...DEFAULT_LAYERS,
      hidden_groups: ["region", "herd", "other"],
      hidden_entities: ["e1", "e2"],
    };
    const next = revealEntity(hidden, props("e1", "herd"), groups);
    expect(isVisible(props("e1", "herd"), next, groups)).toBe(true);
    expect(next.hidden_groups).toEqual(["other"]);
    expect(next.hidden_entities).toEqual(["e2"]);
  });

  it("in the all scope also shows the project row and its ungrouped layer", () => {
    const hidden = {
      ...DEFAULT_LAYERS,
      hidden_groups: [
        projectLayerOf("p"),
        ungroupedLayerOf("p"),
        projectLayerOf("q"),
      ],
    };
    const next = revealEntity(hidden, props("e1", null), groups, true);
    expect(isVisible(props("e1", null), next, groups, true)).toBe(true);
    expect(next.hidden_groups).toEqual([projectLayerOf("q")]);
  });

  it("puts a device in the shown set, a gateway and a feature back on their layers", () => {
    expect(isDeviceShown("d1", revealDevice(DEFAULT_LAYERS, "d1"))).toBe(true);
    const gateways = revealGateway(
      { ...DEFAULT_LAYERS, gateways: false, hidden_gateways: ["g1", "g2"] },
      "g1",
    );
    expect(gateways.gateways).toBe(true);
    expect(gateways.hidden_gateways).toEqual(["g2"]);
    const features = revealFeature(
      {
        ...DEFAULT_LAYERS,
        features: false,
        hidden_feature_types: ["geofence"],
        hidden_features: ["f1"],
      },
      { id: "f1", feature_type: "geofence" },
    );
    expect(features.features).toBe(true);
    expect(features.hidden_feature_types).toEqual([]);
    expect(features.hidden_features).toEqual([]);
  });
});

describe("heard positions of one gateway (phase 19)", () => {
  const all = ["g1", "g2", "g3"];

  it("narrows the coverage query to the gateway, shows it, and widens again", () => {
    const start = {
      ...DEFAULT_LAYERS,
      gateways: false,
      hidden_gateways: ["g2", "g3"],
    };
    const only = toggleOnlyGateway(start, "g2");
    expect(only.coverage).toBe(true);
    expect(only.gateways).toBe(true);
    expect(only.hidden_gateways).toEqual(["g3"]);
    expect(isOnlyGateway(only, "g2")).toBe(true);
    expect(isOnlyGateway(only, "g1")).toBe(false);
    expect(coverageGatewayIds(only, all)).toEqual(["g2"]);
    const back = toggleOnlyGateway(only, "g2");
    expect(back.coverage).toBe(true);
    expect(back.coverage_gateway).toBeNull();
    expect(coverageGatewayIds(back, all)).toEqual(["g1", "g2"]);
    expect(coverageGatewayIds(DEFAULT_LAYERS, all)).toBeUndefined();
  });
});
