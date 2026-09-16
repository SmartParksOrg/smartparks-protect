import { useEffect } from "react";

import type { Entity, EntityGroup } from "@/api/types";
import { type FormState, groupWithSubgroups } from "@/lib/analyses";

/** A link may name a type instead of entities; once the entities are known the form replaces
 * it with the members, capped, so the URL and the estimate speak of entities from then on.
 * Groups stay a choice of their own on the form (Tim, 2026-09-16). */
export function useResolveSubjects(
  state: FormState,
  entities: Entity[] | undefined,
  max: number,
  onChange: (patch: Partial<FormState>) => void,
): void {
  const type = state.type;
  useEffect(() => {
    if (!entities || !type) return;
    const ids = entities
      .filter((e) => e.entity_type_id === type)
      .map((e) => e.id)
      .slice(0, max);
    onChange({ entities: ids, type: null });
    // resolve once per type named in the URL
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, entities]);
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
