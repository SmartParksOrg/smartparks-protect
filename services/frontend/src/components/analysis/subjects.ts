import { useEffect } from "react";

import type { Entity, EntityGroup } from "@/api/types";
import { type FormState, groupWithSubgroups } from "@/lib/analyses";

/** A link may name a group or a type instead of entities ("Analyse grazing" on a group);
 * once the entities are known the form replaces it with the members, capped, so the URL
 * and the estimate speak of entities from then on. */
export function useResolveSubjects(
  state: FormState,
  entities: Entity[] | undefined,
  groups: EntityGroup[] | undefined,
  max: number,
  onChange: (patch: Partial<FormState>) => void,
): void {
  const group = state.group;
  const type = state.type;
  useEffect(() => {
    if (!entities || (!group && !type)) return;
    if (group && !groups) return;
    const inside = group ? groupWithSubgroups(groups ?? [], group) : null;
    const ids = entities
      .filter((e) =>
        inside ? e.group_id && inside.has(e.group_id) : e.entity_type_id === type,
      )
      .map((e) => e.id)
      .slice(0, max);
    onChange({ entities: ids, group: null, type: null });
    // resolve once per group or type named in the URL
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group, type, entities, groups]);
}

/** The entities of a group with its subgroups, for the second herd. */
export function membersOf(
  entities: Entity[] | undefined,
  groups: EntityGroup[] | undefined,
  groupId: string | null,
  max: number,
): string[] {
  if (!groupId || !entities) return [];
  const inside = groupWithSubgroups(groups ?? [], groupId);
  return entities
    .filter((e) => e.group_id && inside.has(e.group_id))
    .map((e) => e.id)
    .slice(0, max);
}
