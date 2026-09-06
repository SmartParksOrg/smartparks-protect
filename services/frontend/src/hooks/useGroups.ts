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

/** Groups as a tree in reading order: each group followed by everything below it, however
 * deep, with its depth. */
export function groupTree(
  groups: EntityGroup[] | undefined,
  parentId: string | null = null,
  depth = 0,
): { group: EntityGroup; depth: number }[] {
  const rows: { group: EntityGroup; depth: number }[] = [];
  for (const group of (groups ?? []).filter(
    (g) => (g.parent_id ?? null) === parentId,
  )) {
    rows.push({ group, depth });
    rows.push(...groupTree(groups, group.id, depth + 1));
  }
  return rows;
}

/** The ids of every group below one, however deep. */
export function descendantIds(
  groups: EntityGroup[] | undefined,
  id: string,
): string[] {
  return groupTree(groups, id, 1).map((r) => r.group.id);
}

/** The ids of the groups above one, nearest first. */
export function ancestorIds(
  groups: EntityGroup[] | undefined,
  id: string,
): string[] {
  const out: string[] = [];
  let current = groups?.find((g) => g.id === id)?.parent_id ?? null;
  while (current && !out.includes(current)) {
    out.push(current);
    current = groups?.find((g) => g.id === current)?.parent_id ?? null;
  }
  return out;
}

/** "North / Herd A / Family": the names from the top down to the group. */
export function groupPath(
  groups: EntityGroup[] | undefined,
  id: string | null | undefined,
): string {
  if (!id) return "";
  const names = [...ancestorIds(groups, id)]
    .reverse()
    .map((a) => groups?.find((g) => g.id === a)?.name ?? "");
  names.push(groups?.find((g) => g.id === id)?.name ?? "");
  return names.filter(Boolean).join(" / ");
}

/** The filter value that means "entities in no group". */
export const UNGROUPED = "__ungrouped__";
