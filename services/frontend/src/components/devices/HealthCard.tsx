import { useTranslation } from "react-i18next";
import { useState } from "react";

import type { DeviceHealth, HealthValue } from "@/api/types";
import { MetricTrend } from "@/components/map/BatteryTrend";
import { useMetricsByKey } from "@/hooks/useMetrics";
import { type TrendSpec, trendSpecFor } from "@/lib/trend";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useNow } from "@/hooks/useNow";
import { formatAgo, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Level colours: state, not identity (frontend conventions). */
const levelClass: Record<string, string> = {
  ok: "text-foreground",
  warn: "text-brand-sand",
  critical: "text-destructive font-semibold",
};

function valueText(v: HealthValue): string {
  const text = v.text ?? (v.value == null ? "" : String(v.value));
  return v.unit && v.kind === "number" ? `${text} ${v.unit}` : text;
}

/** The device's health as the driver declares it (decision D104): one line per field with
 * its level, the time of the last status and last seen. With the project and the device given,
 * a numeric value the registry knows unfolds its trend under the line (Tim, 2026-09-15). */
export function HealthCard({
  health,
  className,
  projectId,
  deviceId,
}: {
  health: DeviceHealth | null | undefined;
  className?: string;
  projectId?: string | null;
  deviceId?: string | null;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const metrics = useMetricsByKey();
  const [openKey, setOpenKey] = useState<string | null>(null);
  if (!health) return null;
  const trends = projectId && deviceId ? { projectId, deviceId } : null;
  return (
    <Card className={className}>
      <CardHeader><CardTitle className="flex items-center gap-2">{t("Health")} <HealthDot level={health.level} /></CardTitle></CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t("Last seen")}</dt><dd title={formatTime(health.last_seen_at)}>{formatAgo(health.last_seen_at, now)}</dd>
          {health.last_status_at && <><dt className="text-muted-foreground">{t("Last status")}</dt><dd title={formatTime(health.last_status_at)}>{formatAgo(health.last_status_at, now)}</dd></>}
          {health.fields.map((f) => (
            <FieldRow
              key={f.key}
              field={f}
              spec={trends && (typeof f.value === "number" || f.key === "movement") ? trendSpecFor(f.key, metrics.get(f.key), t) : null}
              open={openKey === f.key}
              onToggle={() => setOpenKey((k) => (k === f.key ? null : f.key))}
              trends={trends}
            />
          ))}
        </dl>
        {health.fields.length === 0 && <p className="text-xs text-muted-foreground">{t("This device type declares no health fields.")}</p>}
      </CardContent>
    </Card>
  );
}

function FieldRow({
  field,
  spec,
  open,
  onToggle,
  trends,
}: {
  field: HealthValue;
  spec: TrendSpec | null;
  open: boolean;
  onToggle: () => void;
  trends: { projectId: string; deviceId: string } | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <dt className="text-muted-foreground">{field.label}</dt>
      <dd className={cn(levelClass[field.level ?? ""] ?? "")} title={field.at ? formatTime(field.at) : undefined}>
        {spec && trends ? (
          <button
            type="button"
            className="underline underline-offset-2 hover:text-primary"
            title={open ? t("Hide the trend") : t("Show the trend of {{metric}}", { metric: spec.label })}
            aria-expanded={open}
            onClick={onToggle}
          >
            {valueText(field)}
          </button>
        ) : (
          valueText(field)
        )}
      </dd>
      {spec && trends && open && (
        <dd className="col-span-2 rounded-md border bg-muted/30 p-2">
          <MetricTrend projectId={trends.projectId} deviceId={trends.deviceId} spec={spec} />
        </dd>
      )}
    </>
  );
}

export function HealthDot({ level }: { level: string | null | undefined }) {
  const { t } = useTranslation();
  if (!level) return null;
  const tone = level === "critical" ? "bg-destructive" : level === "warn" ? "bg-brand-sand" : "bg-brand-green-light";
  const label = level === "critical" ? t("critical") : level === "warn" ? t("warning") : t("ok");
  return <span className={cn("inline-block size-2.5 rounded-full", tone)} title={label} aria-label={label} />;
}

/** The compact line for lists and the map: battery, temperature, uptime and firmware when present. */
export function HealthLine({ health }: { health: DeviceHealth | null | undefined }) {
  if (!health || health.fields.length === 0) return null;
  const wanted = ["battery_voltage", "movement", "device_temperature", "uptime", "firmware_version"];
  const parts = wanted.map((k) => health.fields.find((f) => f.key === k)).filter((f): f is HealthValue => Boolean(f));
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 text-xs">
      <HealthDot level={health.level} />
      {parts.map((f) => <span key={f.key} className={cn(levelClass[f.level ?? ""] ?? "text-muted-foreground")} title={f.label}>{valueText(f)}</span>)}
    </span>
  );
}
