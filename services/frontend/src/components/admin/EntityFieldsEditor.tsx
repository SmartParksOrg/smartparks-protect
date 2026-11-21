import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { EntityField } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { fieldLabel, type OwnFieldDraft } from "@/lib/entityFields";

const KINDS: EntityField["kind"][] = [
  "text",
  "number",
  "integer",
  "date",
  "choice",
  "boolean",
];

/** The fields of an entity type in its dialog (decision D399): the standard and inherited
 * ones as a read-only line each, then the type's own, which an admin adds, orders, edits
 * and removes. Removing a field leaves the values the entities hold; they read as "Other"
 * from then on (decision D401). */
export function EntityFieldsEditor({
  given,
  value,
  onChange,
}: {
  /** The fields the type has from elsewhere: standard or from the type above it. */
  given: EntityField[];
  value: OwnFieldDraft[];
  onChange: (value: OwnFieldDraft[]) => void;
}) {
  const { t } = useTranslation();
  const kindLabel: Record<EntityField["kind"], string> = {
    text: t("Text"),
    number: t("Number"),
    integer: t("Whole number"),
    date: t("Date"),
    choice: t("Choice"),
    boolean: t("Yes or no"),
  };
  const patch = (index: number, change: Partial<OwnFieldDraft>) =>
    onChange(value.map((d, i) => (i === index ? { ...d, ...change } : d)));
  const move = (index: number, by: number) => {
    const next = [...value];
    const [row] = next.splice(index, 1);
    if (row) next.splice(index + by, 0, row);
    onChange(next);
  };
  return (
    <div className="space-y-3">
      {given.length > 0 && (
        <ul className="space-y-0.5 text-sm text-muted-foreground">
          {given.map((field) => (
            <li key={field.key}>
              {fieldLabel(field, t)}
              {field.unit ? ` (${field.unit})` : ""} · {kindLabel[field.kind]} ·{" "}
              {field.origin === "standard"
                ? t("standard")
                : t("from the type above")}
            </li>
          ))}
        </ul>
      )}
      {value.map((draft, index) => {
        const id = `own-field-${index}`;
        const numeric = draft.kind === "number" || draft.kind === "integer";
        return (
          <div
            key={index}
            className="space-y-2 rounded-md border px-3 pt-3 pb-2"
          >
            <div className="grid gap-2 sm:grid-cols-[1fr_10rem]">
              <Input
                id={id}
                aria-label={t("Field label")}
                placeholder={t("Label, for example Collar colour")}
                value={draft.label}
                onChange={(e) => patch(index, { label: e.target.value })}
              />
              <Select
                value={draft.kind}
                onValueChange={(v) =>
                  patch(index, { kind: v as EntityField["kind"] })
                }
              >
                <SelectTrigger aria-label={t("Kind")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KINDS.map((kind) => (
                    <SelectItem key={kind} value={kind}>
                      {kindLabel[kind]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {numeric && (
              <label className="flex items-center gap-2 text-sm">
                <span className="w-16 shrink-0 text-muted-foreground">
                  {t("Unit")}
                </span>
                <Input
                  placeholder={t("for example cm (optional)")}
                  value={draft.unit}
                  onChange={(e) => patch(index, { unit: e.target.value })}
                />
              </label>
            )}
            {draft.kind === "choice" && (
              <label className="flex items-center gap-2 text-sm">
                <span className="w-16 shrink-0 text-muted-foreground">
                  {t("Choices")}
                </span>
                <Input
                  placeholder={t("separated by commas")}
                  value={draft.choices}
                  onChange={(e) => patch(index, { choices: e.target.value })}
                />
              </label>
            )}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              <label className="inline-flex items-center gap-2">
                <Switch
                  size="sm"
                  checked={draft.panel}
                  onCheckedChange={(panel) => patch(index, { panel })}
                />
                {t("On the map panel")}
              </label>
              {draft.kind === "text" && (
                <label className="inline-flex items-center gap-2">
                  <Switch
                    size="sm"
                    checked={draft.search}
                    onCheckedChange={(search) => patch(index, { search })}
                  />
                  {t("In the search")}
                </label>
              )}
              <span className="ml-auto inline-flex">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("Move up")}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("Move down")}
                  disabled={index === value.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("Remove field")}
                  onClick={() => onChange(value.filter((_, i) => i !== index))}
                >
                  <Trash2 className="size-4" />
                </Button>
              </span>
            </div>
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() =>
          onChange([
            ...value,
            {
              key: "",
              label: "",
              kind: "text",
              unit: "",
              choices: "",
              panel: false,
              search: false,
            },
          ])
        }
      >
        <Plus className="size-4" /> {t("Add a field")}
      </Button>
    </div>
  );
}
