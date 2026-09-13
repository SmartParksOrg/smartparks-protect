import type { EntityGroup } from "@/api/types";

/** The groups as a flat list in tree order with the depth of each. */
export function orderTree(
  groups: EntityGroup[],
): { group: EntityGroup; depth: number }[] {
  const byParent = new Map<string | null, EntityGroup[]>();
  for (const g of groups) {
    const key = g.parent_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), g]);
  }
  const out: { group: EntityGroup; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const g of byParent.get(parent) ?? []) {
      out.push({ group: g, depth });
      walk(g.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}
