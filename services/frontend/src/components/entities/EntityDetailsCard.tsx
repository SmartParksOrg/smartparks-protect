import { Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { EntityField } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fieldLabel,
  fieldValueText,
  otherValueText,
  splitAttributes,
} from "@/lib/entityFields";

/** What the entity's fields say (decision D399), on the entity page: the filled fields of
 * its type in the order of the form, then the values no field defines under "Other"
 * (decision D401). Nothing at all while no field has a value and nobody here may fill one. */
export function EntityDetailsCard({
  fields,
  attributes,
  onEdit,
}: {
  fields: EntityField[];
  attributes: Record<string, unknown> | null | undefined;
  /** Opens the entity dialog; absent for a person who may not change the entity. */
  onEdit?: () => void;
}) {
  const { t } = useTranslation();
  const { filled, other } = splitAttributes(fields, attributes);
  const empty = filled.length === 0 && other.length === 0;
  if (empty && (!onEdit || fields.length === 0)) return null;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>{t("Details")}</CardTitle>
        {onEdit && (
          <Button variant="ghost" size="sm" onClick={onEdit}>
            <Pencil className="size-4" /> {t("Edit")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {empty ? (
          <p className="text-sm text-muted-foreground">
            {t("Nothing filled in yet.")}
          </p>
        ) : (
          <dl className="grid grid-cols-[fit-content(45%)_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
            {filled.map(({ field, value }) => (
              <div key={field.key} className="contents">
                <dt className="text-muted-foreground">
                  {fieldLabel(field, t)}
                </dt>
                <dd className="break-words">
                  {fieldValueText(field, value, t)}
                </dd>
              </div>
            ))}
            {other.length > 0 && (
              <dt className="col-span-2 mt-2 font-medium">{t("Other")}</dt>
            )}
            {other.map(({ key, value }) => (
              <div key={key} className="contents">
                <dt className="font-mono text-xs text-muted-foreground">
                  {key}
                </dt>
                <dd className="break-words">{otherValueText(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
