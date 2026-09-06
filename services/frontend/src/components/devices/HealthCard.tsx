import { useTranslation } from "react-i18next";

import type { DeviceHealth, HealthValue } from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
 * its level, the time of the last status and last seen. */
export function HealthCard({ health, className }: { health: DeviceHealth | null | undefined; className?: string }) {
  const { t } = useTranslation();
  if (!health) return null;
  return (
    <Card className={className}>
      <CardHeader><CardTitle className="flex items-center gap-2">{t("Health")} <HealthDot level={health.level} /></CardTitle></CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t("Last seen")}</dt><dd title={formatTime(health.last_seen_at)}>{formatAgo(health.last_seen_at)}</dd>
          {health.last_status_at && <><dt className="text-muted-foreground">{t("Last status")}</dt><dd title={formatTime(health.last_status_at)}>{formatAgo(health.last_status_at)}</dd></>}
          {health.fields.map((f) => (
            <FieldRow key={f.key} field={f} />
          ))}
        </dl>
        {health.fields.length === 0 && <p className="text-xs text-muted-foreground">{t("This device type declares no health fields.")}</p>}
      </CardContent>
    </Card>
  );
}

function FieldRow({ field }: { field: HealthValue }) {
  return (
    <>
      <dt className="text-muted-foreground">{field.label}</dt>
      <dd className={cn(levelClass[field.level ?? ""] ?? "")} title={field.at ? formatTime(field.at) : undefined}>{valueText(field)}</dd>
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
  const wanted = ["battery_voltage", "device_temperature", "uptime", "firmware_version"];
  const parts = wanted.map((k) => health.fields.find((f) => f.key === k)).filter((f): f is HealthValue => Boolean(f));
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 text-xs">
      <HealthDot level={health.level} />
      {parts.map((f) => <span key={f.key} className={cn(levelClass[f.level ?? ""] ?? "text-muted-foreground")} title={f.label}>{valueText(f)}</span>)}
    </span>
  );
}
