import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { RadioTower } from "lucide-react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CoverageResponse, GatewayDetail } from "@/api/types";
import { HeardButton, MapPanel, PanelRow } from "@/components/map/MapObjectPanel";
import { GatewayLocationDialog } from "@/components/network/GatewayLocationDialog";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";
import { gatewayCoords, locationSourceLabel } from "@/lib/gateways";

const HOURS = 168;

/**
 * A gateway on the live map (phase 19): the network's side of the picture, with the devices it
 * heard in the last week and the heard positions toggle (decision D373), which draws every
 * position this gateway heard over the period, like a track on an entity's panel.
 */
export function GatewayPanel({
  projectId,
  gatewayId,
  allProjects,
  serverAdmin,
  now,
  wasHidden,
  onClose,
  heard,
  onToggleHeard,
  coverage,
}: {
  projectId: string;
  gatewayId: string;
  allProjects: boolean;
  serverAdmin: boolean;
  now: number;
  wasHidden: boolean;
  onClose: () => void;
  /** The heard positions of this gateway are on (decision D373). */
  heard: boolean;
  onToggleHeard: () => void;
  /** The selection's read, for the count beside the button. */
  coverage: CoverageResponse | undefined;
}) {
  const { t } = useTranslation();
  const { can } = usePermissions(projectId);
  const [placing, setPlacing] = useState(false);
  const detail = useQuery({
    queryKey: queryKeys.gateway(projectId, gatewayId, HOURS),
    queryFn: () =>
      api.get<GatewayDetail>(
        `/api/v1/projects/${projectId}/gateways/${gatewayId}`,
        { query: { hours: HOURS } },
      ),
  });
  const g = detail.data?.gateway;
  const share = coverage?.gateways.find((c) => c.gateway_id === gatewayId);
  const coordinates = g?.geometry
    ? ((g.geometry as { coordinates: [number, number] }).coordinates ?? null)
    : null;
  return (
    <MapPanel
      title={g?.display_name ?? t("Gateway")}
      titleTo={`/projects/${projectId}/network/gateways/${gatewayId}`}
      subtitle={
        g ? `${g.data_source_name ?? ""} · ${g.external_id}` : undefined
      }
      picture={
        <span className="flex size-9 items-center justify-center rounded-md bg-muted">
          <RadioTower className="size-5 text-primary" />
        </span>
      }
      note={
        wasHidden
          ? t("Hidden in the layers panel until now; it stays shown.")
          : undefined
      }
      onClose={onClose}
      summary={
        g ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusBadge value={g.status} />
            <span title={formatTime(g.last_seen_at)}>
              {t("Seen {{ago}}", { ago: formatAgo(g.last_seen_at, now) })}
            </span>
            <span className="text-muted-foreground">
              {t("{{count}} receptions", { count: g.receptions })}
            </span>
            {g.device_id && (
              <Link
                className="underline"
                to={`/projects/${projectId}/devices/${g.device_id}`}
              >
                {t("Offload station device")}
              </Link>
            )}
          </div>
        ) : undefined
      }
      footer={
        <>
          <HeardButton on={heard} onToggle={onToggleHeard} gateway />
          {g && can("project:write") && !allProjects && (
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              onClick={() => setPlacing(true)}
            >
              {coordinates ? t("Change location") : t("Set location")}
            </Button>
          )}
          {heard && (
            <span className="text-xs text-muted-foreground">
              {coverage && share
                ? t("{{count}} heard positions in the period", { count: share.heard })
                : coverage
                  ? t("none in the period")
                  : t("Loading…")}
            </span>
          )}
        </>
      }
    >
      {detail.isPending && <PanelRow label={t("Loading…")}>{""}</PanelRow>}
      {detail.isError && (
        <PanelRow label={t("Gateway")} className="text-destructive">
          {detail.error.message}
        </PanelRow>
      )}
      {g && (
        <>
          <PanelRow label={t("Status")}>
            <StatusBadge value={g.status} />
          </PanelRow>
          <PanelRow label={t("Last seen")} title={formatTime(g.last_seen_at)}>
            {formatAgo(g.last_seen_at, now)}
          </PanelRow>
          <PanelRow
            label={t("Location")}
            title={
              g.location_source
                ? t("from {{source}}", {
                    source: locationSourceLabel(g.location_source, t),
                  })
                : undefined
            }
          >
            {coordinates ? (
              <>
                <span className="font-mono text-xs">{gatewayCoords(g, 5)}</span>
                {g.location_source === "admin" && (
                  <span className="text-muted-foreground">
                    {" "}
                    {t("(set by hand)")}
                  </span>
                )}
              </>
            ) : (
              <span className="text-muted-foreground">{t("none known")}</span>
            )}
          </PanelRow>
          <PanelRow label={t("Last 7 days")}>
            {t("{{count}} receptions", { count: g.receptions })}
            {", "}
            {t("{{count}} devices", { count: g.devices })}
            {g.mean_rssi != null ? `, ${Math.round(g.mean_rssi)} dBm` : ""}
          </PanelRow>
          {(detail.data?.devices.length ?? 0) > 0 && (
            <PanelRow label={t("Heard")}>
              <ul>
                {detail.data?.devices.slice(0, 5).map((d) => (
                  <li key={d.device_id ?? d.device_name ?? ""}>
                    {d.device_id ? (
                      <Link
                        className="underline"
                        to={
                          allProjects
                            ? `/admin/devices/${d.device_id}`
                            : `/projects/${projectId}/devices/${d.device_id}?tab=traffic`
                        }
                      >
                        {d.device_name ?? d.device_id}
                      </Link>
                    ) : (
                      t("unknown device")
                    )}
                    <span className="text-muted-foreground">
                      {" "}
                      {d.receptions}
                      {d.mean_rssi != null
                        ? `, ${Math.round(d.mean_rssi)} dBm`
                        : ""}
                    </span>
                  </li>
                ))}
                {(detail.data?.devices.length ?? 0) > 5 && (
                  <li className="text-muted-foreground">
                    {t("and {{count}} more", {
                      count: (detail.data?.devices.length ?? 0) - 5,
                    })}
                  </li>
                )}
              </ul>
            </PanelRow>
          )}
          {placing && (
            <GatewayLocationDialog
              projectId={projectId}
              gateway={g}
              onClose={() => setPlacing(false)}
            />
          )}
          <PanelRow label={t("More")}>
            <Link
              className="underline"
              to={`/projects/${projectId}/network/gateways/${gatewayId}`}
            >
              {t("gateway page")}
            </Link>
            {" · "}
            <Link
              className="underline"
              to={`/projects/${projectId}/network/gateways`}
            >
              {t("gateways")}
            </Link>
            {serverAdmin && (
              <>
                {" · "}
                <Link className="underline" to="/admin/data-sources">
                  {t("data source")}
                </Link>
              </>
            )}
            {(g.links ?? []).map((l) => (
              <span key={l.key}>
                {" · "}
                <a
                  className="underline"
                  href={l.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {l.label}
                </a>
              </span>
            ))}
          </PanelRow>
        </>
      )}
    </MapPanel>
  );
}
