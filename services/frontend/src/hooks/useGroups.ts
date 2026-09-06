import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityGroup } from "@/api/types";

export function useGroups(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.groups(projectId ?? ""),
    queryFn: () =>
      api.get<EntityGroup[]>(`/api/v1/projects/${projectId}/groups`),
    enabled: Boolean(projectId),
  });
}

/** Groups as a tree in reading order: each top-level group followed by its subgroups. */
export function groupTree(
  groups: EntityGroup[] | undefined,
): { group: EntityGroup; depth: number }[] {
  const rows: { group: EntityGroup; depth: number }[] = [];
  for (const parent of (groups ?? []).filter((g) => !g.parent_id)) {
    rows.push({ group: parent, depth: 0 });
    for (const child of (groups ?? []).filter((g) => g.parent_id === parent.id))
      rows.push({ group: child, depth: 1 });
  }
  return rows;
}

/** The filter value that means "entities in no group". */
export const UNGROUPED = "__ungrouped__";
