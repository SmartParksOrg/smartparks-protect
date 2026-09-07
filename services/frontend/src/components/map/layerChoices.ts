import type { EntityGroup } from "@/api/types";
import type {
  EntityFeatureProperties,
  EventFeatureProperties,
} from "@/components/map/layers";
import { ancestorIds, descendantIds } from "@/hooks/useGroups";

/** What the map shows for one project, kept per user (preference `map_layers`). Hidden sets
 * rather than shown sets, so a new group, entity, feature or event type appears until someone
 * hides it. */
export interface LayerChoices {
  hidden_groups: string[];
  hidden_entities: string[];
  features: boolean;
  hidden_feature_types: string[];
  hidden_features: string[];
  events: boolean;
  hidden_event_types: string[];
  gateways: boolean;
  hidden_gateways: string[];
  coverage: boolean;
  coverage_hours: number;
  /** The device layer (decision D113) is a shown set: every device is off until switched on. */
  shown_devices: string[];
}

export const UNGROUPED_LAYER = "ungrouped";
export const DEFAULT_LAYERS: LayerChoices = {
  hidden_groups: [],
  hidden_entities: [],
  features: true,
  hidden_feature_types: [],
  hidden_features: [],
  events: true,
  hidden_event_types: [],
  gateways: true,
  hidden_gateways: [],
  coverage: false,
  coverage_hours: 168,
  shown_devices: [],
};

export function isDeviceShown(deviceId: string, choices: LayerChoices): boolean {
  return choices.shown_devices.includes(deviceId);
}

export function toggleDevice(
  choices: LayerChoices,
  deviceId: string,
  show: boolean,
): LayerChoices {
  const rest = choices.shown_devices.filter((id) => id !== deviceId);
  return { ...choices, shown_devices: show ? [...rest, deviceId] : rest };
}

/** Every listed device on (the Devices tab's "Show all"); devices that arrive later stay off. */
export function showDevices(
  choices: LayerChoices,
  deviceIds: string[],
): LayerChoices {
  return {
    ...choices,
    shown_devices: [...new Set([...choices.shown_devices, ...deviceIds])],
  };
}

export function hideAllDevices(choices: LayerChoices): LayerChoices {
  return { ...choices, shown_devices: [] };
}

export const layerOf = (props: EntityFeatureProperties): string =>
  props.group_id ?? UNGROUPED_LAYER;

/** A group shows unless it or a group above it is hidden. */
export function isGroupShown(
  id: string,
  choices: LayerChoices,
  groups: EntityGroup[] | undefined,
): boolean {
  if (choices.hidden_groups.includes(id)) return false;
  return !ancestorIds(groups, id).some((a) =>
    choices.hidden_groups.includes(a),
  );
}

/** A feature shows unless its entity or its group (or one above it) is hidden. */
export function isVisible(
  props: EntityFeatureProperties,
  choices: LayerChoices,
  groups: EntityGroup[] | undefined,
): boolean {
  if (choices.hidden_entities.includes(props.entity_id)) return false;
  return isGroupShown(layerOf(props), choices, groups);
}

export function isFeatureVisible(
  feature: { id: string; feature_type: string },
  choices: LayerChoices,
): boolean {
  return (
    choices.features &&
    !choices.hidden_feature_types.includes(feature.feature_type) &&
    !choices.hidden_features.includes(feature.id)
  );
}

export function isGatewayVisible(
  gatewayId: string,
  choices: LayerChoices,
): boolean {
  return choices.gateways && !choices.hidden_gateways.includes(gatewayId);
}

export function isEventVisible(
  props: EventFeatureProperties,
  choices: LayerChoices,
): boolean {
  return (
    choices.events && !choices.hidden_event_types.includes(props.event_type)
  );
}

const without = (list: string[], ids: string[]) =>
  list.filter((id) => !ids.includes(id));
const withAll = (list: string[], ids: string[]) => [
  ...new Set([...list, ...ids]),
];

/** Show or hide a group; hiding takes everything below along. Showing a group under a hidden
 * one shows the chain above it and hides the other branches instead. */
export function toggleGroup(
  choices: LayerChoices,
  id: string,
  show: boolean,
  groups: EntityGroup[] | undefined,
): LayerChoices {
  const below = descendantIds(groups, id);
  if (!show)
    return {
      ...choices,
      hidden_groups: withAll(choices.hidden_groups, [id, ...below]),
    };
  let hidden = without(choices.hidden_groups, [id, ...below]);
  let child = id;
  for (const parent of ancestorIds(groups, id)) {
    if (hidden.includes(parent)) {
      const siblings = (groups ?? [])
        .filter((g) => g.parent_id === parent && g.id !== child)
        .map((g) => g.id);
      hidden = withAll(without(hidden, [parent]), siblings);
    }
    child = parent;
  }
  return { ...choices, hidden_groups: hidden };
}

/** Only this group (or only the ungrouped entities): everything else hidden, no entity hidden. */
export function onlyGroup(
  choices: LayerChoices,
  id: string,
  groups: EntityGroup[] | undefined,
): LayerChoices {
  const keep = new Set([
    id,
    ...ancestorIds(groups, id),
    ...descendantIds(groups, id),
  ]);
  const hidden = [UNGROUPED_LAYER, ...(groups ?? []).map((g) => g.id)].filter(
    (x) => !keep.has(x),
  );
  return { ...choices, hidden_groups: hidden, hidden_entities: [] };
}

export function toggleEntity(
  choices: LayerChoices,
  id: string,
  show: boolean,
): LayerChoices {
  return {
    ...choices,
    hidden_entities: show
      ? without(choices.hidden_entities, [id])
      : withAll(choices.hidden_entities, [id]),
  };
}

/** Every entity layer hidden (the panel's "Hide all"). */
export function hideAllEntities(
  choices: LayerChoices,
  groups: EntityGroup[] | undefined,
): LayerChoices {
  return {
    ...choices,
    hidden_groups: [UNGROUPED_LAYER, ...(groups ?? []).map((g) => g.id)],
    hidden_entities: [],
  };
}

export function toggleInList(
  list: string[],
  id: string,
  show: boolean,
): string[] {
  return show ? without(list, [id]) : withAll(list, [id]);
}

/** Showing one row under a switched-off parent switches the parent on and hides the other rows
 * instead, so a click on a child always does what it says. */
function onlyThis(
  hidden: string[],
  id: string,
  siblings: string[],
  parentWasOn: boolean,
): string[] {
  const base = parentWasOn ? hidden : withAll(hidden, siblings);
  return without(base, [id]);
}

export function showGateway(
  choices: LayerChoices,
  id: string,
  all: string[],
): LayerChoices {
  return {
    ...choices,
    gateways: true,
    hidden_gateways: onlyThis(
      choices.hidden_gateways,
      id,
      all,
      choices.gateways,
    ),
  };
}

export function showFeatureType(
  choices: LayerChoices,
  type: string,
  allTypes: string[],
): LayerChoices {
  return {
    ...choices,
    features: true,
    hidden_feature_types: onlyThis(
      choices.hidden_feature_types,
      type,
      allTypes,
      choices.features,
    ),
  };
}

export function showFeature(
  choices: LayerChoices,
  feature: { id: string; feature_type: string },
  allOfType: string[],
  allTypes: string[],
): LayerChoices {
  const typeOn =
    choices.features &&
    !choices.hidden_feature_types.includes(feature.feature_type);
  const next = typeOn
    ? choices
    : showFeatureType(choices, feature.feature_type, allTypes);
  return {
    ...next,
    hidden_features: onlyThis(
      choices.hidden_features,
      feature.id,
      allOfType,
      typeOn,
    ),
  };
}

export function showEventType(
  choices: LayerChoices,
  type: string,
  allTypes: string[],
): LayerChoices {
  return {
    ...choices,
    events: true,
    hidden_event_types: onlyThis(
      choices.hidden_event_types,
      type,
      allTypes,
      choices.events,
    ),
  };
}

/** Show one entity: its group chain comes on (other branches hidden) and, when the group was
 * hidden, the other entities of that group stay hidden. */
export function showEntity(
  choices: LayerChoices,
  props: EntityFeatureProperties,
  groups: EntityGroup[] | undefined,
  siblings: string[],
): LayerChoices {
  const layer = layerOf(props);
  const groupWasOn = isGroupShown(layer, choices, groups);
  const next = groupWasOn ? choices : toggleGroup(choices, layer, true, groups);
  return {
    ...next,
    hidden_entities: onlyThis(
      choices.hidden_entities,
      props.entity_id,
      siblings,
      groupWasOn,
    ),
  };
}
