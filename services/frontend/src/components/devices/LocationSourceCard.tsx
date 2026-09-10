import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";

type Source = "device" | "network" | "device_else_network";

/** Which positions decide the current position of an entity or a device (decision D164): the
 * device's own fixes, the network's locations, or the device with the network standing in
 * after a period without a fix. Device only by default; a network location never reaches the
 * main map unless a person chose it here. */
export function LocationSourceCard({
  path,
  value,
  fallbackHours,
  invalidate,
  canEdit,
}: {
  /** The object's API path, `/api/v1/projects/{id}/entities/{id}` or `/api/v1/devices/{id}`. */
  path: string;
  value: string;
  fallbackHours: number;
  invalidate: readonly (readonly unknown[])[];
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const [source, setSource] = useState<Source>(value as Source);
  const [hours, setHours] = useState(String(fallbackHours));
  useEffect(() => {
    setSource(value as Source);
    setHours(String(fallbackHours));
  }, [value, fallbackHours]);
  const save = useMutationToast({
    mutationFn: () =>
      api.patch(path, {
        body: {
          location_source: source,
          location_fallback_hours: Math.min(
            720,
            Math.max(1, Number(hours) || 24),
          ),
        },
      }),
    invalidate: [...invalidate],
    success: t("Location source saved"),
  });
  const dirty = source !== value || Number(hours) !== fallbackHours;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Location source")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          {t(
            "Which positions decide where this is shown: the device's own fixes, or a location the network provides (an Iridium estimate, a LoRaWAN geolocation), which is coarse.",
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={source}
            onValueChange={(v) => setSource(v as Source)}
            disabled={!canEdit}
          >
            <SelectTrigger
              className="h-9 w-64"
              aria-label={t("Location source")}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="device">{t("Device fixes only")}</SelectItem>
              <SelectItem value="device_else_network">
                {t("Device, else the network")}
              </SelectItem>
              <SelectItem value="network">
                {t("Network locations too")}
              </SelectItem>
            </SelectContent>
          </Select>
          {source === "device_else_network" && (
            <label className="flex items-center gap-2">
              {t("after")}
              <Input
                type="number"
                min={1}
                max={720}
                className="h-9 w-20"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
                disabled={!canEdit}
                aria-label={t("Hours without a device fix")}
              />
              {t("hours without a fix")}
            </label>
          )}
          {canEdit && dirty && (
            <Button
              size="sm"
              onClick={() => save.mutate()}
              disabled={save.isPending}
            >
              {t("Save")}
            </Button>
          )}
        </div>
        {source !== "device" && (
          <Callout kind="info">
            {t(
              "A network location is drawn with its radius and named as an estimate in the panels, the tracks and the exports.",
            )}
          </Callout>
        )}
      </CardContent>
    </Card>
  );
}
