/** Entity types with sub-types (decision D166): a type (Wildlife) holds sub-types (Elephant)
 * one level deep, an entity references the most specific row, and a project hides the ones it
 * does not want in its settings (decision D168). Pure helpers over the type list. */

export interface TypeLike {
  id: string;
  label: string;
  icon_key: string;
  parent_id?: string | null;
}

export const HIDDEN_TYPES_KEY = "hidden_entity_type_ids";

export function hiddenTypeIds(settings: unknown): Set<string> {
  const raw = (settings as Record<string, unknown> | null | undefined)?.[HIDDEN_TYPES_KEY];
  return new Set(Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : []);
}

const byLabel = <T extends TypeLike>(a: T, b: T) => a.label.localeCompare(b.label);

/** The types without a parent, by label. */
export function topLevel<T extends TypeLike>(types: T[]): T[] {
  return types.filter((t) => !t.parent_id).sort(byLabel);
}

/** The sub-types of one type, by label. */
export function subtypesOf<T extends TypeLike>(types: T[], parentId: string): T[] {
  return types.filter((t) => t.parent_id === parentId).sort(byLabel);
}

/** What a project may choose from: a hidden type takes its sub-types with it. */
export function visibleTypes<T extends TypeLike>(types: T[], hidden: Set<string>): T[] {
  return types.filter((t) => !hidden.has(t.id) && !(t.parent_id && hidden.has(t.parent_id)));
}

/** The chosen row split into the type and the sub-type the dialog shows. */
export function splitSelection<T extends TypeLike>(types: T[], id: string): { typeId: string; subtypeId: string } {
  const row = types.find((t) => t.id === id);
  if (!row) return { typeId: "", subtypeId: "" };
  return row.parent_id ? { typeId: row.parent_id, subtypeId: row.id } : { typeId: row.id, subtypeId: "" };
}

/** "Wildlife · Elephant" for a sub-type, the label alone for a type. */
export function typePath<T extends TypeLike>(types: T[], id: string | null | undefined): string {
  const row = types.find((t) => t.id === id);
  if (!row) return "";
  const parent = row.parent_id ? types.find((t) => t.id === row.parent_id) : undefined;
  return parent ? `${parent.label} · ${row.label}` : row.label;
}
