import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { RadioTower } from "lucide-react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CoverageResponse, GatewayDetail } from "@/api/types";
import {
  isOnlyGateway,
  type LayerChoices,
  toggleOnlyGateway,
} from "@/components/map/layerChoices";
import { MapPanel, PanelRow } from "@/components/map/MapObjectPanel";
import { Button } from "@/components/ui/button";
import { formatAgo, formatTime } from "@/lib/format";

const HOURS = 168;

/**
 * A gateway on the live map (phase 19): the network's side of the picture, with the devices it
 * heard in the last week and "Show heard positions", which narrows the coverage layer to this
 * gateway alone (the Coverage tab reflects it).
 */
export function GatewayPanel({
  projectId,
  gatewayId,
  allProjects,
  serverAdmin,
  now,
  wasHidden,
  panelOpen,
  onClose,
  choices,
  coverage,
  onChange,
}: {
  projectId: string;
  gatewayId: string;
  allProjects: boolean;
  serverAdmin: boolean;
  now: number;
  wasHidden: boolean;
  panelOpen: boolean;
  onClose: () => void;
  choices: LayerChoices;
  coverage: CoverageResponse | undefined;
  onChange: (next: LayerChoices) => void;
}) {
  const { t } = useTranslation();
  const detail = useQuery({
    queryKey: queryKeys.gateway(projectId, gatewayId, HOURS),
    queryFn: () =>
      api.get<GatewayDetail>(
        `/api/v1/projects/${projectId}/gateways/${gatewayId}`,
        { query: { hours: HOURS } },
      ),
  });
  const g = detail.data?.gateway;
  const only = isOnlyGateway(choices, gatewayId);
  const heard = coverage?.gateways.find((c) => c.gateway_id === gatewayId);
  const coordinates = g?.geometry
    ? ((g.geometry as { coordinates: [number, number] }).coordinates ?? null)
    : null;
  return (
    <MapPanel
      title={g?.display_name ?? t("Gateway")}
      titleTo={`/projects/${projectId}/network/gateways`}
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
      panelOpen={panelOpen}
      footer={
        <>
          <Button
            variant={only ? "default" : "outline"}
            size="sm"
            className="h-8"
            aria-pressed={only}
            onClick={() => onChange(toggleOnlyGateway(choices, gatewayId))}
          >
            {only ? t("All heard positions") : t("Show heard positions")}
          </Button>
          {only && (
            <span className="text-xs text-muted-foreground">
              {coverage && heard
                ? t("{{count}} heard positions, {{share}}% of the view", {
                    count: heard.heard,
                    share: Math.round(heard.share * 100),
                  })
                : coverage
                  ? t("none in view")
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
          <PanelRow label={t("Status")}>{g.status}</PanelRow>
          <PanelRow label={t("Last seen")} title={formatTime(g.last_seen_at)}>
            {formatAgo(g.last_seen_at, now)}
          </PanelRow>
          {coordinates && (
            <PanelRow label={t("Location")}>
              <span className="font-mono text-xs">
                {coordinates[1].toFixed(5)}, {coordinates[0].toFixed(5)}
              </span>
              {g.location_source && (
                <span className="text-muted-foreground">
                  {" "}
                  ({g.location_source})
                </span>
              )}
            </PanelRow>
          )}
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
                            : `/projects/${projectId}/devices/${d.device_id}?tab=network`
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
          <PanelRow label={t("More")}>
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
