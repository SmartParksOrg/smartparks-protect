import type { EntityGroup } from "@/api/types";
import type { EntityFeatureProperties } from "@/components/map/layers";

/** What the map shows for one project, kept per user (preference `map_layers`). Hidden sets
 * rather than shown sets, so a new group or entity appears until someone hides it. */
export interface LayerChoices {
  hidden_groups: string[];
  hidden_entities: string[];
  features: boolean;
  events: boolean;
}

export const UNGROUPED_LAYER = "ungrouped";
export const DEFAULT_LAYERS: LayerChoices = {
  hidden_groups: [],
  hidden_entities: [],
  features: true,
  events: true,
};

export const layerOf = (props: EntityFeatureProperties): string =>
  props.group_id ?? UNGROUPED_LAYER;

/** A feature shows unless its entity, its group or its group's parent is hidden. */
export function isVisible(
  props: EntityFeatureProperties,
  choices: LayerChoices,
  groups: EntityGroup[] | undefined,
): boolean {
  if (choices.hidden_entities.includes(props.entity_id)) return false;
  const layer = layerOf(props);
  if (choices.hidden_groups.includes(layer)) return false;
  const parent = groups?.find((g) => g.id === layer)?.parent_id;
  return !(parent && choices.hidden_groups.includes(parent));
}

const without = (list: string[], ids: string[]) =>
  list.filter((id) => !ids.includes(id));
const withAll = (list: string[], ids: string[]) => [
  ...new Set([...list, ...ids]),
];

/** Show or hide a group; a top-level group takes its subgroups along. Showing a subgroup whose
 * parent is hidden shows the parent and hides the siblings instead. */
export function toggleGroup(
  choices: LayerChoices,
  id: string,
  show: boolean,
  groups: EntityGroup[] | undefined,
): LayerChoices {
  const group = groups?.find((g) => g.id === id);
  const children = (groups ?? [])
    .filter((g) => g.parent_id === id)
    .map((g) => g.id);
  if (!show)
    return {
      ...choices,
      hidden_groups: withAll(choices.hidden_groups, [id, ...children]),
    };
  let hidden = without(choices.hidden_groups, [id, ...children]);
  if (group?.parent_id && hidden.includes(group.parent_id)) {
    const siblings = (groups ?? [])
      .filter((g) => g.parent_id === group.parent_id && g.id !== id)
      .map((g) => g.id);
    hidden = withAll(without(hidden, [group.parent_id]), siblings);
  }
  return { ...choices, hidden_groups: hidden };
}

/** Only this group (or only the ungrouped entities): everything else hidden, no entity hidden. */
export function onlyGroup(
  choices: LayerChoices,
  id: string,
  groups: EntityGroup[] | undefined,
): LayerChoices {
  const group = groups?.find((g) => g.id === id);
  const keep = new Set([
    id,
    ...(group?.parent_id ? [group.parent_id] : []),
    ...(groups ?? []).filter((g) => g.parent_id === id).map((g) => g.id),
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
