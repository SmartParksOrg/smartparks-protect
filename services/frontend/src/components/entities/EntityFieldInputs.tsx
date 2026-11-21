import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { EntityField } from "@/api/types";
import { Field } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  choiceLabel,
  fieldHelp,
  fieldLabel,
  otherValueText,
  splitAttributes,
} from "@/lib/entityFields";

const NONE = "__none__";

/** The inputs of an entity's fields in the dialog (decision D399): one per field of the
 * chosen type, following the type as it changes. The draft is the whole document, so a
 * value of a field the type lacks is not lost: it shows under "Other" with a remove button
 * (decision D401). Numbers are kept as typed and turned into numbers on save. */
export function EntityFieldInputs({
  fields,
  draft,
  onChange,
}: {
  fields: EntityField[];
  draft: Record<string, unknown>;
  onChange: (draft: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const { other } = splitAttributes(fields, draft);
  const set = (key: string, value: unknown) =>
    onChange({ ...draft, [key]: value });
  if (fields.length === 0 && other.length === 0) return null;
  return (
    <>
      {fields.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {fields.map((field) => {
            const id = `field-${field.key}`;
            const value = draft[field.key];
            const label = field.unit
              ? `${fieldLabel(field, t)} (${field.unit})`
              : fieldLabel(field, t);
            return (
              <Field
                key={field.key}
                label={label}
                htmlFor={id}
                hint={fieldHelp(field, t)}
              >
                {field.kind === "choice" || field.kind === "boolean" ? (
                  <Select
                    value={value == null || value === "" ? NONE : String(value)}
                    onValueChange={(v) =>
                      set(
                        field.key,
                        v === NONE
                          ? null
                          : field.kind === "boolean"
                            ? v === "true"
                            : v,
                      )
                    }
                  >
                    <SelectTrigger id={id}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>{t("Not set")}</SelectItem>
                      {field.kind === "boolean" ? (
                        <>
                          <SelectItem value="true">{t("Yes")}</SelectItem>
                          <SelectItem value="false">{t("No")}</SelectItem>
                        </>
                      ) : (
                        field.choices.map((choice) => (
                          <SelectItem key={choice.value} value={choice.value}>
                            {choiceLabel(field, choice.value, t)}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id={id}
                    type={field.kind === "date" ? "date" : "text"}
                    inputMode={
                      field.kind === "number"
                        ? "decimal"
                        : field.kind === "integer"
                          ? "numeric"
                          : undefined
                    }
                    value={value == null ? "" : String(value)}
                    onChange={(e) => set(field.key, e.target.value)}
                  />
                )}
              </Field>
            );
          })}
        </div>
      )}
      {other.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-sm font-medium">{t("Other")}</p>
          <p className="text-xs text-muted-foreground">
            {t("Kept from another type or set through the API.")}
          </p>
          <ul className="space-y-1 text-sm">
            {other.map(({ key, value }) => (
              <li key={key} className="flex items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">
                  {key}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {otherValueText(value)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("Remove {{name}}", { name: key })}
                  onClick={() => set(key, null)}
                >
                  <X className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
