import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Activity } from "lucide-react";

import { api } from "@/api/client";
import type { DeviceStateRead } from "@/api/types";
import { MapPanel, PanelRow } from "@/components/map/MapObjectPanel";
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

/**
 * The device's last status (Tim, 2026-09-13): what the driver declares as health lines, with
 * their levels, then every other value the status carried, and the way to its source event.
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
        <PanelRow
          key={f.key}
          label={f.label}
          className={cn(levelClass[f.level ?? ""] ?? "")}
        >
          {f.text ?? plain(f.value)}
          {f.unit && f.kind === "number" ? ` ${f.unit}` : ""}
        </PanelRow>
      ))}
      {rest.map(([key, value]) => (
        <PanelRow key={key} label={words(key)}>
          <span className="font-mono text-xs">{plain(value)}</span>
        </PanelRow>
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
