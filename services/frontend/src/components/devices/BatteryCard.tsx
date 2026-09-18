import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceBattery } from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { batterySourceLabel } from "@/lib/battery";

const DEFAULT = "__default__";

/**
 * The battery this device carries (decision D248). A voltage means nothing without the
 * chemistry: 3.60 V is a healthy primary lithium cell and a half-empty lithium-ion one, so the
 * type decides the thresholds behind the colour on the map and the share of charge shown beside
 * the voltage. Unset, the device follows its device type, and that follows what the device
 * family usually carries.
 */
export function BatteryCard({
  deviceId,
  canEdit,
}: {
  deviceId: string;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const battery = useQuery({
    queryKey: queryKeys.deviceBattery(deviceId),
    queryFn: () => api.get<DeviceBattery>(`/api/v1/devices/${deviceId}/battery`),
  });
  const save = useMutationToast({
    mutationFn: (key: string | null) =>
      api.put<DeviceBattery>(`/api/v1/devices/${deviceId}/battery`, {
        body: { battery_type: key },
      }),
    invalidate: [
      queryKeys.deviceBattery(deviceId),
      queryKeys.device(deviceId),
      ["devices"],
    ],
    success: (b) =>
      b.source === "device"
        ? t("Battery type saved")
        : t("The battery type is cleared; the device type decides again"),
  });
  const b = battery.data;
  const chosen = b?.types.find((type) => type.key === b.battery_type);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Battery")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!b ? (
          <p className="text-muted-foreground">{t("Loading…")}</p>
        ) : (
          <>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-muted-foreground">{t("Last reading")}</dt>
              <dd>
                {b.voltage == null
                  ? t("none yet")
                  : b.percent == null
                    ? `${b.voltage.toFixed(2)} V`
                    : t("{{volts}} V, about {{percent}}% left", {
                        volts: b.voltage.toFixed(2),
                        percent: b.percent,
                      })}
              </dd>
              <dt className="text-muted-foreground">{t("Battery type")}</dt>
              <dd>
                {chosen ? chosen.label : t("not known")}
                <span className="text-muted-foreground">
                  {" "}
                  ({batterySourceLabel(b.source, t)})
                </span>
              </dd>
              {chosen && (
                <>
                  <dt className="text-muted-foreground">{t("Warns below")}</dt>
                  <dd>
                    {t("{{warn}} V, critical below {{critical}} V", {
                      warn: chosen.warn_v.toFixed(2),
                      critical: chosen.critical_v.toFixed(2),
                    })}
                  </dd>
                </>
              )}
            </dl>
            {chosen && <p className="text-muted-foreground">{chosen.note}</p>}
            {!chosen && (
              <p className="text-muted-foreground">
                {t(
                  "Without a battery type the voltage is judged by the driver's own thresholds, which fit one chemistry only.",
                )}
              </p>
            )}
            {canEdit && (
              <Select
                value={b.battery_type ?? DEFAULT}
                disabled={save.isPending}
                onValueChange={(v) => save.mutate(v === DEFAULT ? null : v)}
              >
                <SelectTrigger
                  className="w-full sm:w-80"
                  aria-label={t("Battery type")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT}>
                    {b.default_battery_type
                      ? t("Follow {{source}}", {
                          source: batterySourceLabel(b.default_source, t),
                        })
                      : t("Not known")}
                  </SelectItem>
                  {b.types.map((type) => (
                    <SelectItem key={type.key} value={type.key}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
