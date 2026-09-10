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
  /** Satellite sessions (decision D158): the Iridium network's location estimates as circles,
   * over the coverage period; a small field so the preference stays small. */
  satellite?: boolean;
  /** Heard positions of one gateway alone (phase 19); null or absent means every ticked gateway.
   * A field rather than a hidden list, so the markers stay and the preference stays small. */
  coverage_gateway?: string | null;
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
  satellite: false,
  shown_devices: [],
};

export function isDeviceShown(
  deviceId: string,
  choices: LayerChoices,
): boolean {
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

/** These devices off (a project row's switch in the all scope); the rest stay as they are. */
export function hideDevices(
  choices: LayerChoices,
  deviceIds: string[],
): LayerChoices {
  return {
    ...choices,
    shown_devices: choices.shown_devices.filter(
      (id) => !deviceIds.includes(id),
    ),
  };
}

export function hideAllDevices(choices: LayerChoices): LayerChoices {
  return { ...choices, shown_devices: [] };
}

/** The layer an entity sits in: its group, else the ungrouped layer; in the all scope the
 * ungrouped layer is per project (decision D117). */
export const layerOf = (
  props: EntityFeatureProperties,
  perProject = false,
): string =>
  props.group_id ??
  (perProject && props.project_id
    ? ungroupedLayerOf(props.project_id)
    : UNGROUPED_LAYER);

export const projectLayerOf = (projectId: string): string =>
  `project:${projectId}`;
export const ungroupedLayerOf = (projectId: string): string =>
  `ungrouped:${projectId}`;

/** The project a layer belongs to, when the layer is a group or a per-project ungrouped layer. */
export function projectOfLayer(
  id: string,
  groups: EntityGroup[] | undefined,
): string | null {
  if (id.startsWith("ungrouped:")) return id.slice("ungrouped:".length);
  if (id.startsWith("project:")) return id.slice("project:".length);
  return groups?.find((g) => g.id === id)?.project_id ?? null;
}

/** Showing a layer inside a hidden project shows the project as well. */
export function withProjectShown(
  choices: LayerChoices,
  id: string,
  groups: EntityGroup[] | undefined,
): LayerChoices {
  const project = projectOfLayer(id, groups);
  if (!project) return choices;
  return {
    ...choices,
    hidden_groups: choices.hidden_groups.filter(
      (g) => g !== projectLayerOf(project),
    ),
  };
}

/** A group shows unless it or a group above it is hidden. */
export function isGroupShown(
  id: string,
  choices: LayerChoices,
  groups: EntityGroup[] | undefined,
): boolean {
  if (choices.hidden_groups.includes(id)) return false;
  const project = projectOfLayer(id, groups);
  if (project && choices.hidden_groups.includes(projectLayerOf(project)))
    return false;
  return !ancestorIds(groups, id).some((a) =>
    choices.hidden_groups.includes(a),
  );
}

/** A feature shows unless its entity or its group (or one above it) is hidden. */
export function isVisible(
  props: EntityFeatureProperties,
  choices: LayerChoices,
  groups: EntityGroup[] | undefined,
  perProject = false,
): boolean {
  if (choices.hidden_entities.includes(props.entity_id)) return false;
  return isGroupShown(layerOf(props, perProject), choices, groups);
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
  projectIds: string[] = [],
): LayerChoices {
  // in the all scope the layers are per project: their rows and ungrouped layers go too
  const perProject = projectIds.flatMap((id) => [
    projectLayerOf(id),
    ungroupedLayerOf(id),
  ]);
  return {
    ...choices,
    hidden_groups: [
      UNGROUPED_LAYER,
      ...(groups ?? []).map((g) => g.id),
      ...perProject,
    ],
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

/** Show all and Hide all of a tab: the layer's switch with its hidden lists cleared, or the
 * switch off; ticking one item under a switched-off layer then shows only that item. */
export function showAllFeatures(choices: LayerChoices): LayerChoices {
  return {
    ...choices,
    features: true,
    hidden_feature_types: [],
    hidden_features: [],
  };
}

export function hideAllFeatures(choices: LayerChoices): LayerChoices {
  return { ...choices, features: false };
}

export function showAllEvents(choices: LayerChoices): LayerChoices {
  return { ...choices, events: true, hidden_event_types: [] };
}

export function hideAllEvents(choices: LayerChoices): LayerChoices {
  return { ...choices, events: false };
}

export function showAllGateways(choices: LayerChoices): LayerChoices {
  return { ...choices, gateways: true, hidden_gateways: [] };
}

export function hideAllGateways(choices: LayerChoices): LayerChoices {
  return { ...choices, gateways: false };
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

/** A "show on map" link must land on a visible object (phase 19): the object and the layers
 * above it are switched on and the choice is kept, so the person sees what they asked for and
 * the panel can say it was hidden. In the all scope the project row and the per-project
 * ungrouped layer count as layers above an entity (decision D117). */
export function revealEntity(
  choices: LayerChoices,
  props: EntityFeatureProperties,
  groups: EntityGroup[] | undefined,
  perProject = false,
): LayerChoices {
  const layer = layerOf(props, perProject);
  const above = [layer, ...ancestorIds(groups, layer)];
  if (perProject && props.project_id)
    above.push(projectLayerOf(props.project_id));
  return {
    ...choices,
    hidden_groups: without(choices.hidden_groups, above),
    hidden_entities: without(choices.hidden_entities, [props.entity_id]),
  };
}

export function revealDevice(
  choices: LayerChoices,
  deviceId: string,
): LayerChoices {
  return toggleDevice(choices, deviceId, true);
}

export function revealGateway(
  choices: LayerChoices,
  gatewayId: string,
): LayerChoices {
  return {
    ...choices,
    gateways: true,
    hidden_gateways: without(choices.hidden_gateways, [gatewayId]),
  };
}

export function revealFeature(
  choices: LayerChoices,
  feature: { id: string; feature_type: string },
): LayerChoices {
  return {
    ...choices,
    features: true,
    hidden_feature_types: without(choices.hidden_feature_types, [
      feature.feature_type,
    ]),
    hidden_features: without(choices.hidden_features, [feature.id]),
  };
}

/** Whether the coverage layer shows the heard positions of exactly this gateway (the gateway
 * panel's "Show heard positions"). */
export function isOnlyGateway(
  choices: LayerChoices,
  gatewayId: string,
): boolean {
  return choices.coverage && choices.coverage_gateway === gatewayId;
}

/** Heard positions of one gateway alone: the coverage layer on and narrowed to the gateway,
 * which is shown as well; a second call widens the layer back to every ticked gateway. */
export function toggleOnlyGateway(
  choices: LayerChoices,
  gatewayId: string,
): LayerChoices {
  if (isOnlyGateway(choices, gatewayId))
    return { ...choices, coverage: true, coverage_gateway: null };
  return {
    ...revealGateway(choices, gatewayId),
    coverage: true,
    coverage_gateway: gatewayId,
  };
}

/** The gateway ids the coverage query filters on: the one gateway, else every ticked one, else
 * nothing (every gateway). */
export function coverageGatewayIds(
  choices: LayerChoices,
  all: string[],
): string[] | undefined {
  if (choices.coverage_gateway) return [choices.coverage_gateway];
  if (choices.hidden_gateways.length === 0) return undefined;
  return all.filter((id) => !choices.hidden_gateways.includes(id));
}
