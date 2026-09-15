import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Activity } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import type { DeviceStateRead } from "@/api/types";
import { MetricTrend } from "@/components/map/BatteryTrend";
import { MapPanel, PanelRow } from "@/components/map/MapObjectPanel";
import { useMetricsByKey } from "@/hooks/useMetrics";
import { type TrendSpec, trendSpecFor } from "@/lib/trend";
import { Button } from "@/components/ui/button";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const levelClass: Record<string, string> = {
  ok: "",
  warn: "text-brand-sand",
  critical: "text-destructive font-semibold",
};

/** A raw state key as words: `firmware_version` reads "firmware version". */
const words = (key: string) => key.replace(/_/g, " ");
const plain = (value: unknown): string =>
  value == null
    ? ""
    : typeof value === "object"
      ? JSON.stringify(value)
      : typeof value === "number"
        ? String(Number.isInteger(value) ? value : Number(value.toFixed(3)))
        : String(value);

/** One value of the status: plain, or a button that unfolds the metric's trend under the
 * row (Tim, 2026-09-15) when the registry knows the value as a numeric metric. */
function StatusRow({
  label,
  text,
  className,
  mono,
  spec,
  open,
  onToggle,
  projectId,
  deviceId,
  until,
}: {
  label: string;
  text: string;
  className?: string;
  mono?: boolean;
  spec: TrendSpec | null;
  open: boolean;
  onToggle: () => void;
  projectId: string;
  deviceId: string;
  until?: string | null;
}) {
  const { t } = useTranslation();
  const value = <span className={mono ? "font-mono text-xs" : undefined}>{text}</span>;
  return (
    <>
      <PanelRow label={label} className={className}>
        {spec ? (
          <button
            type="button"
            className="underline underline-offset-2 hover:text-primary"
            title={open ? t("Hide the trend") : t("Show the trend of {{metric}}", { metric: spec.label })}
            aria-expanded={open}
            onClick={onToggle}
          >
            {value}
          </button>
        ) : (
          value
        )}
      </PanelRow>
      {spec && open && (
        <div className="col-span-2 rounded-md border bg-muted/30 p-2">
          <MetricTrend projectId={projectId} deviceId={deviceId} spec={spec} until={until} />
        </div>
      )}
    </>
  );
}

/**
 * The device's last status (Tim, 2026-09-13): what the driver declares as health lines, with
 * their levels, then every other value the status carried, and the way to its source event.
 * A numeric value the registry knows unfolds its trend (Tim, 2026-09-15).
 */
export function StatePanel({
  projectId,
  deviceId,
  onClose,
  onOpenSourceEvent,
}: {
  projectId: string;
  deviceId: string;
  onClose: () => void;
  onOpenSourceEvent: (id: number, ingestedAt: string) => void;
}) {
  const { t } = useTranslation();
  const state = useQuery({
    queryKey: ["projects", projectId, "device-state", deviceId],
    queryFn: () =>
      api.get<DeviceStateRead>(
        `/api/v1/projects/${projectId}/devices/${deviceId}/state`,
      ),
    retry: false,
  });
  const s = state.data;
  const declared = new Set(s?.health.fields.map((f) => f.key) ?? []);
  const rest = Object.entries(s?.state ?? {}).filter(([k]) => !declared.has(k));
  const metrics = useMetricsByKey();
  const [openKey, setOpenKey] = useState<string | null>(null);
  const toggle = (key: string) => setOpenKey((k) => (k === key ? null : key));
  const specOf = (key: string, value: unknown): TrendSpec | null =>
    typeof value === "number" || key === "movement" ? trendSpecFor(key, metrics.get(key), t) : null;
  return (
    <MapPanel
      title={s?.device_name ?? t("Last status")}
      titleTo={s ? `/projects/${projectId}/devices/${s.device_id}` : undefined}
      subtitle={
        s?.time ? t("Status at {{time}}", { time: formatTime(s.time) }) : t("Last status")
      }
      picture={
        <span className="flex size-9 items-center justify-center rounded-full bg-muted">
          <Activity className="size-5 text-primary" />
        </span>
      }
      onClose={onClose}
      footer={
        s?.source_event_id != null && s.source_event_ingested_at ? (
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => onOpenSourceEvent(s.source_event_id!, s.source_event_ingested_at!)}
          >
            {t("Source event")}
          </Button>
        ) : undefined
      }
    >
      {state.isPending && <PanelRow label={t("Loading…")}>{""}</PanelRow>}
      {state.isError && (
        <PanelRow label={t("Status")} className="text-destructive">
          {t("No status from this device yet")}
        </PanelRow>
      )}
      {s?.health.fields.map((f) => (
        <StatusRow
          key={f.key}
          label={f.label}
          text={`${f.text ?? plain(f.value)}${f.unit && f.kind === "number" ? ` ${f.unit}` : ""}`}
          className={cn(levelClass[f.level ?? ""] ?? "")}
          spec={specOf(f.key, f.value)}
          open={openKey === f.key}
          onToggle={() => toggle(f.key)}
          projectId={projectId}
          deviceId={deviceId}
          until={s?.health.last_seen_at ?? s?.time}
        />
      ))}
      {rest.map(([key, value]) => (
        <StatusRow
          key={key}
          label={words(key)}
          text={plain(value)}
          mono
          spec={specOf(key, value)}
          open={openKey === key}
          onToggle={() => toggle(key)}
          projectId={projectId}
          deviceId={deviceId}
          until={s?.health.last_seen_at ?? s?.time}
        />
      ))}
      {s && s.health.fields.length === 0 && rest.length === 0 && (
        <PanelRow label={t("Status")}>{t("The status carried no values")}</PanelRow>
      )}
      {s && (
        <PanelRow label={t("More")}>
          <Link className="underline" to={`/projects/${projectId}/devices/${s.device_id}?tab=data`}>
            {t("records")}
          </Link>
        </PanelRow>
      )}
    </MapPanel>
  );
}
