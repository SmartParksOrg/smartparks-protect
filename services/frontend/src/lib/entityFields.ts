/** The fields of an entity by its type (decisions D399 to D405): a type's `fields` say what
 * can be typed in, the entity's `attributes` hold the values, and a key no field defines is
 * kept and shown under "Other". Pure helpers for the dialog, the entity page and the map
 * panel. */
import type { EntityField, EntityType } from "@/api/types";
import { t } from "@/lib/i18nMark";

type Translate = (text: string) => string;

/** The texts of the standard fields, marked for the translation extractor: the API sends
 * them in English and `fieldLabel` translates them. `tests/shared/test_entity_fields.py`
 * fails when a standard text is missing from the catalogues. An own field shows as the
 * admin typed it. */
export const STANDARD_FIELD_TEXTS = [
  t("ID number"),
  t("The number or code this animal has in your own records"),
  t("Sex"),
  t("Female"),
  t("Male"),
  t("Unknown"),
  t("Birth year"),
  t("Age class"),
  t("Juvenile"),
  t("Subadult"),
  t("Adult"),
  t("VHF frequency"),
  t("The frequency of a VHF tag on the animal"),
  t("Ear tag number"),
  t("The official number, 4 to 20 letters and digits, such as NL 123456789012"),
  t("Breed"),
  t("Weight"),
  t("Licence plate"),
  t("Brand"),
  t("Model"),
  t("Fleet number"),
  t("Call sign"),
  t("Team"),
  t("Asset number"),
];

export function fieldsOfType(
  types: EntityType[] | undefined,
  typeId: string | null | undefined,
): EntityField[] {
  return types?.find((x) => x.id === typeId)?.fields ?? [];
}

const text = (field: EntityField, value: string, translate: Translate) =>
  field.origin === "standard" ? translate(value) : value;

export function fieldLabel(field: EntityField, translate: Translate): string {
  return text(field, field.label, translate);
}

export function fieldHelp(
  field: EntityField,
  translate: Translate,
): string | undefined {
  return field.help ? text(field, field.help, translate) : undefined;
}

export function choiceLabel(
  field: EntityField,
  value: string,
  translate: Translate,
): string {
  const choice = field.choices.find((c) => c.value === value);
  return choice ? text(field, choice.label, translate) : value;
}

const isEmpty = (value: unknown) =>
  value == null || (typeof value === "string" && value.trim() === "");

/** A stored value as a person reads it: the choice's label, yes or no, a number with its
 * unit. */
export function fieldValueText(
  field: EntityField,
  value: unknown,
  translate: Translate,
): string {
  if (field.kind === "boolean")
    return value ? translate(t("Yes")) : translate(t("No"));
  if (field.kind === "choice")
    return choiceLabel(field, String(value), translate);
  return field.unit ? `${String(value)} ${field.unit}` : String(value);
}

/** A value of a key no field defines, as text. */
export function otherValueText(value: unknown): string {
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** The document split into the type's filled fields, in the order of the form, and the
 * rest (decision D401). */
export function splitAttributes(
  fields: EntityField[],
  attributes: Record<string, unknown> | null | undefined,
): {
  filled: { field: EntityField; value: unknown }[];
  other: { key: string; value: unknown }[];
} {
  const document = attributes ?? {};
  const keys = new Set(fields.map((f) => f.key));
  return {
    filled: fields
      .filter((field) => !isEmpty(document[field.key]))
      .map((field) => ({ field, value: document[field.key] })),
    other: Object.entries(document)
      .filter(([key, value]) => !keys.has(key) && !isEmpty(value))
      .map(([key, value]) => ({ key, value })),
  };
}

/** The number fields of every type, each key once: what the grazing analysis may weight
 * its animals by (decision D406), a weight in kilograms first of all. */
export function numericFields(types: EntityType[] | undefined): EntityField[] {
  const byKey = new Map<string, EntityField>();
  for (const type of types ?? [])
    for (const field of type.fields ?? [])
      if (
        (field.kind === "number" || field.kind === "integer") &&
        !byKey.has(field.key)
      )
        byKey.set(field.key, field);
  return [...byKey.values()];
}

/** What the search finds beside the name (decision D406): the values of the fields marked
 * for it, such as a licence plate. The Entities list filters its rows on this text as well,
 * so a row the server found by its plate is not dropped by the table's own filter. */
export function searchText(
  fields: EntityField[],
  attributes: Record<string, unknown> | null | undefined,
): string {
  return splitAttributes(
    fields.filter((field) => field.search),
    attributes,
  )
    .filled.map(({ value }) => String(value))
    .join(" ");
}

/** The document as the API takes it: what was typed into a number field as a number, a
 * comma read as the decimal mark, an empty value left out. `invalid` names the first
 * number field whose text is no number. */
export function toAttributes(
  fields: EntityField[],
  draft: Record<string, unknown>,
): { attributes: Record<string, unknown>; invalid: EntityField | null } {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const attributes: Record<string, unknown> = {};
  let invalid: EntityField | null = null;
  for (const [key, value] of Object.entries(draft)) {
    if (isEmpty(value)) continue;
    const field = byKey.get(key);
    const numeric = field?.kind === "number" || field?.kind === "integer";
    if (field && numeric && typeof value === "string") {
      const number = Number(value.trim().replace(",", "."));
      if (Number.isNaN(number)) invalid ??= field;
      else attributes[key] = number;
      continue;
    }
    attributes[key] = typeof value === "string" ? value.trim() : value;
  }
  return { attributes, invalid };
}

/** An own field as the editor holds it: the API's definition with the choices as one text. */
export interface OwnFieldDraft {
  key: string;
  label: string;
  kind: EntityField["kind"];
  unit: string;
  /** The choices' labels, separated by commas. */
  choices: string;
  panel: boolean;
  search: boolean;
  /** The rest of a stored definition (min, max, help, the choices' values), sent back as it
   * came since the editor has no input for it. */
  stored?: EntityField;
}

/** A key from a label: "Collar colour" gives `collar_colour`. */
export function keyOf(label: string): string {
  const key = label
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 63);
  return /^[a-z]/.test(key) ? key : key ? `f_${key}`.slice(0, 63) : "";
}

export function toDraft(field: EntityField): OwnFieldDraft {
  return {
    key: field.key,
    label: field.label,
    kind: field.kind,
    unit: field.unit ?? "",
    choices: field.choices.map((c) => c.label).join(", "),
    panel: field.panel,
    search: field.search,
    stored: field,
  };
}

/** The drafts as `attribute_schema.fields`. A stored field keeps its key, since the
 * entities' documents hold it; a new one takes its key from its label. A choice keeps the
 * value it had under the same label. */
export function toDefinitions(
  drafts: OwnFieldDraft[],
): Record<string, unknown>[] {
  return drafts.map((draft) => {
    const numeric = draft.kind === "number" || draft.kind === "integer";
    const before = draft.stored;
    const sameKind = before?.kind === draft.kind;
    return {
      key: before ? before.key : keyOf(draft.label),
      label: draft.label.trim(),
      kind: draft.kind,
      ...(numeric && draft.unit.trim() ? { unit: draft.unit.trim() } : {}),
      ...(numeric && sameKind && before.min != null ? { min: before.min } : {}),
      ...(numeric && sameKind && before.max != null ? { max: before.max } : {}),
      ...(before?.help ? { help: before.help } : {}),
      ...(draft.kind === "choice"
        ? {
            choices: draft.choices
              .split(",")
              .map((label) => label.trim())
              .filter(Boolean)
              .map((label) => ({
                value:
                  before?.choices.find((c) => c.label === label)?.value ??
                  keyOf(label),
                label,
              })),
          }
        : {}),
      panel: draft.panel,
      search: draft.kind === "text" && draft.search,
    };
  });
}
