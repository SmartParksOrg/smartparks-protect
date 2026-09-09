import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { MapPin } from "lucide-react";
import { Link } from "react-router";

import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { PointRead } from "@/api/types";
import { MapPanel, PanelRow } from "@/components/map/MapObjectPanel";
import { measurementText } from "@/components/map/measurementText";
import { Button } from "@/components/ui/button";
import { formatTime } from "@/lib/format";
import { recordsHref } from "@/lib/records";
import { projectFor } from "@/lib/scope";

/**
 * A track point (phase 19): the position at that device time with the measurements of the same
 * moment, who it belongs to, and the way to the source event, the trace and the Data tabs.
 */
export function PointPanel({
  projectId,
  ownerId,
  kind,
  time,
  onClose,
  onOpenSourceEvent,
  onOpenTrace,
}: {
  projectId: string;
  ownerId: string;
  kind: "entity" | "device";
  time: string;
  onClose: () => void;
  onOpenSourceEvent: (id: number, ingestedAt: string) => void;
  onOpenTrace: (traceId: string) => void;
}) {
  const { t } = useTranslation();
  const point = useQuery({
    queryKey: queryKeys.pointAt(projectId, { ownerId, kind, time }),
    queryFn: () =>
      api.get<PointRead>(`/api/v1/projects/${projectId}/positions/at`, {
        query: {
          time,
          ...(kind === "entity"
            ? { entity_id: ownerId }
            : { device_id: ownerId }),
        },
      }),
    retry: false,
  });
  const p = point.data?.position;
  const project = projectFor(projectId, p?.project_id ?? undefined);
  const coordinates = p?.geometry?.coordinates as [number, number] | undefined;
  const gone = point.error instanceof ApiError && point.error.status === 404;
  const atParam = `at=${encodeURIComponent(p?.time ?? time)}`;
  return (
    <MapPanel
      title={
        point.data?.entity_name ?? point.data?.device_name ?? t("Track point")
      }
      titleTo={
        p
          ? p.entity_id
            ? `/projects/${project}/entities/${p.entity_id}`
            : `/projects/${project}/devices/${p.device_id}`
          : undefined
      }
      subtitle={formatTime(time)}
      picture={
        <span className="flex size-9 items-center justify-center rounded-full bg-muted">
          <MapPin className="size-5 text-primary" />
        </span>
      }
      onClose={onClose}
      footer={
        p ? (
          <>
            {p.source_event_id != null && p.source_event_ingested_at && (
              <Button
                variant="outline"
                size="sm"
                className="h-8"
                onClick={() =>
                  onOpenSourceEvent(
                    p.source_event_id!,
                    p.source_event_ingested_at!,
                  )
                }
              >
                {t("Source event")}
              </Button>
            )}
            {p.trace_id && (
              <Button
                variant="outline"
                size="sm"
                className="h-8"
                onClick={() => onOpenTrace(p.trace_id!)}
              >
                {t("Trace")}
              </Button>
            )}
          </>
        ) : undefined
      }
    >
      {point.isPending && <PanelRow label={t("Loading…")}>{""}</PanelRow>}
      {gone && (
        <PanelRow label={t("Position")}>
          {t("No position at that time any more; the track may have changed.")}
        </PanelRow>
      )}
      {point.isError && !gone && (
        <PanelRow label={t("Position")} className="text-destructive">
          {point.error.message}
        </PanelRow>
      )}
      {p && (
        <>
          <PanelRow label={t("Position")}>
            {coordinates ? (
              <span className="font-mono text-xs">
                {coordinates[1].toFixed(5)}, {coordinates[0].toFixed(5)}
              </span>
            ) : (
              t("none")
            )}
            {p.accuracy_m != null && (
              <span className="text-muted-foreground">
                {" "}
                {t("±{{value}} m", { value: p.accuracy_m })}
              </span>
            )}
          </PanelRow>
          {p.altitude_m != null && (
            <PanelRow label={t("Altitude")}>
              {t("{{value}} m", { value: Math.round(p.altitude_m) })}
            </PanelRow>
          )}
          {p.speed_mps != null && (
            <PanelRow label={t("Speed")}>
              {t("{{value}} km/h", { value: (p.speed_mps * 3.6).toFixed(1) })}
            </PanelRow>
          )}
          {p.satellites != null && (
            <PanelRow label={t("Satellites")}>{p.satellites}</PanelRow>
          )}
          {point.data?.measurements.map((m) => (
            <PanelRow key={m.metric_key} label={m.label}>
              {measurementText(m)}
            </PanelRow>
          ))}
          <PanelRow label={t("Entity")}>
            {p.entity_id ? (
              <Link
                className="underline"
                to={`/projects/${project}/entities/${p.entity_id}?tab=data&${atParam}`}
              >
                {point.data?.entity_name ?? t("entity")}
              </Link>
            ) : (
              t("none")
            )}
          </PanelRow>
          <PanelRow label={t("Device")}>
            <Link
              className="underline"
              to={`/projects/${project}/devices/${p.device_id}?tab=data&${atParam}`}
            >
              {point.data?.device_name ?? t("device")}
            </Link>
          </PanelRow>
          <PanelRow label={t("Records")}>
            <Link
              className="underline"
              to={recordsHref(project, {
                devices: [p.device_id],
                at: p.time ?? time,
              })}
            >
              {t("Every record at this time")}
            </Link>
          </PanelRow>
          {(p.curated_fields?.length ?? 0) > 0 && (
            <PanelRow label={t("Curated")}>
              {p.curated_fields?.join(", ")}
            </PanelRow>
          )}
        </>
      )}
    </MapPanel>
  );
}
