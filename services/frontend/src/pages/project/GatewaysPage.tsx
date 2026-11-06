import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { MapPin } from "lucide-react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceConnectivity, Gateway } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatAgo } from "@/lib/format";
import {
  gatewayCoords,
  isOffloadStation,
  isRelay,
  locationSourceLabel,
} from "@/lib/gateways";

/** Every figure on the page covers the last 30 days, and nobody picks a window (Tim,
 * 2026-09-30): the gateway's own last seen has no window at all, so a gateway that heard
 * nothing in a month still says when the network last heard from it. */
const HOURS = 24 * 30;

const coords = (g: Gateway) => gatewayCoords(g);
const signal = (
  rssi: number | null | undefined,
  snr: number | null | undefined,
) =>
  rssi == null && snr == null ? "" : `${rssi ?? "?"} dBm / ${snr ?? "?"} dB`;

/** Gateways and connectivity health (architecture 20): which gateways hear the project's
 * devices, and how well each device is covered. A row opens the gateway's page (D369). */
export function GatewaysPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab =
    params.get("tab") === "connectivity" ? "connectivity" : "gateways";
  const hours = HOURS;
  // the source filter (Tim, 2026-09-12): one data source's gateways, or all of them
  const sourceFilter = params.get("source") ?? "all";
  const base = `/api/v1/projects/${projectId}`;
  const gateways = useQuery({
    queryKey: queryKeys.gateways(projectId, hours),
    queryFn: () =>
      api.get<Gateway[]>(`${base}/gateways`, { query: { hours, limit: 500 } }),
    refetchInterval: 30_000,
  });
  const connectivity = useQuery({
    queryKey: queryKeys.connectivity(projectId, hours),
    queryFn: () =>
      api.get<DeviceConnectivity[]>(`${base}/connectivity`, {
        query: { hours, limit: 500 },
      }),
    enabled: tab === "connectivity",
    refetchInterval: 30_000,
  });
  const sources = Array.from(
    new Map(
      (gateways.data ?? []).map((g) => [
        g.data_source_id,
        g.data_source_name ?? g.data_source_id,
      ]),
    ),
  ).sort((a, b) => a[1].localeCompare(b[1]));
  const shown =
    sourceFilter === "all"
      ? gateways.data
      : gateways.data?.filter((g) => g.data_source_id === sourceFilter);
  const silent = shown?.filter((g) => g.receptions === 0).length ?? 0;

  const columns: ColumnDef<Gateway, unknown>[] = [
    {
      header: t("Gateway"),
      accessorKey: "display_name",
      cell: ({ row }) => (
        <span>
          <span className="font-medium">{row.original.display_name}</span>
          {row.original.display_name !== row.original.external_id && (
            <span className="ml-2 font-mono text-xs text-muted-foreground">
              {row.original.external_id}
            </span>
          )}
          {isRelay(row.original) && (
            <Badge
              variant="outline"
              className="ml-2 align-middle"
              title={t(
                "A Gateway Mesh relay: no backhaul of its own, its uplinks reach the network through a border gateway and count there",
              )}
            >
              {t("Relay (mesh)")}
            </Badge>
          )}
          {isOffloadStation(row.original) && (
            <Badge
              variant="outline"
              className="ml-2 align-middle"
              title={t(
                "An offload station: a RangerEdge whose SD card holds the frames trackers offloaded to it",
              )}
            >
              {t("Offload station")}
            </Badge>
          )}
          {row.original.device_id && (
            <Link
              className="ml-2 text-xs underline"
              to={`/projects/${projectId}/devices/${row.original.device_id}`}
            >
              {t("device")}
            </Link>
          )}
        </span>
      ),
    },
    {
      header: t("Status"),
      accessorKey: "status",
      cell: ({ getValue }) => <StatusBadge value={getValue<string>()} />,
    },
    {
      // the platform's own word on the gateway (its heartbeats, or any reception), apart from
      // what it heard of this project's devices (Tim, 2026-09-30)
      header: t("Last seen"),
      accessorKey: "last_seen_at",
      cell: ({ getValue }) => (
        <span
          title={t(
            "When the network last heard from the gateway itself, whatever it received",
          )}
        >
          {formatAgo(getValue<string | null>())}
        </span>
      ),
    },
    { header: t("Source"), accessorKey: "data_source_name" },
    { header: t("Receptions"), accessorKey: "receptions" },
    { header: t("Devices"), accessorKey: "devices" },
    {
      header: t("Mean signal"),
      id: "signal",
      cell: ({ row }) => signal(row.original.mean_rssi, row.original.mean_snr),
    },
    {
      // the newest reception of this project's devices in the last 30 days, whatever the
      // window: a day without a burst must not read as "never"
      header: t("Last reception"),
      accessorKey: "last_reception_at",
      cell: ({ getValue }) => {
        const value = getValue<string | null>();
        return value ? (
          formatAgo(value)
        ) : (
          <span className="text-muted-foreground">{t("none in 30 days")}</span>
        );
      },
    },
    {
      header: t("Location"),
      id: "location",
      cell: ({ row }) => (
        <span
          className="font-mono text-xs"
          title={
            row.original.location_source
              ? t("from {{source}}", {
                  source: locationSourceLabel(row.original.location_source, t),
                })
              : undefined
          }
        >
          {coords(row.original)}
          {row.original.location_source === "admin" && (
            <span className="ml-1 font-sans text-muted-foreground">
              {t("(set by hand)")}
            </span>
          )}
        </span>
      ),
    },
  ];
  const deviceColumns: ColumnDef<DeviceConnectivity, unknown>[] = [
    {
      header: t("Device"),
      accessorKey: "device_name",
      cell: ({ row }) => (
        <a
          className="underline"
          href={`/projects/${projectId}/devices/${row.original.device_id}?tab=traffic`}
          onClick={(e) => e.stopPropagation()}
        >
          {row.original.device_name ?? row.original.device_id}
        </a>
      ),
    },
    {
      header: t("Gateways"),
      accessorKey: "gateway_count",
      cell: ({ row }) => (
        <span
          className={row.original.gateway_count < 2 ? "text-destructive" : ""}
        >
          {row.original.gateway_count}
        </span>
      ),
    },
    { header: t("Uplinks"), accessorKey: "uplinks" },
    {
      header: t("Best gateway"),
      id: "best",
      cell: ({ row }) => (
        <span>
          {row.original.best_gateway_name}
          {row.original.best_gateway_share != null && (
            <span className="ml-1 text-xs text-muted-foreground">
              {Math.round(row.original.best_gateway_share * 100)}{" "}
              {t("% of uplinks")}
            </span>
          )}
        </span>
      ),
    },
    {
      header: t("Mean signal"),
      id: "signal",
      cell: ({ row }) => signal(row.original.mean_rssi, row.original.mean_snr),
    },
    {
      header: t("Last reception"),
      accessorKey: "last_reception_at",
      cell: ({ getValue }) => formatAgo(getValue<string | null>()),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("Gateways")}
        description={t(
          "The gateways of this project's networks, which of them hear its devices, and how well every device is covered. Network health is not device health: a device can be healthy but poorly connected.",
        )}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to={`/projects/${projectId}/map?gateways=1`}>
              <MapPin className="size-4" /> {t("Show on live map")}
            </Link>
          </Button>
        }
      />
      <Page>
        <div className="flex flex-wrap items-center gap-3">
          <Tabs
            value={tab}
            onValueChange={(v) =>
              setParams(
                (p) => {
                  p.set("tab", v);
                  return p;
                },
                { replace: true },
              )
            }
          >
            <TabsList>
              <TabsTrigger value="gateways">{t("Gateways")}</TabsTrigger>
              <TabsTrigger value="connectivity">
                {t("Device connectivity")}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          {tab === "gateways" && sources.length > 1 && (
            <Select
              value={sourceFilter}
              onValueChange={(v) =>
                setParams(
                  (p) => {
                    if (v === "all") p.delete("source");
                    else p.set("source", v);
                    return p;
                  },
                  { replace: true },
                )
              }
            >
              <SelectTrigger className="w-48" aria-label={t("Source")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("All sources")}</SelectItem>
                {sources.map(([id, name]) => (
                  <SelectItem key={id} value={id}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
        {(gateways.error ?? connectivity.error) && (
          <Callout kind="error">
            {(gateways.error ?? connectivity.error)?.message}
          </Callout>
        )}
        {tab === "gateways" ? (
          <DataTable
            columns={columns}
            data={shown}
            defaultHiddenSmall={[
              "last_seen_at",
              "signal",
              "last_reception_at",
              "location",
            ]}
            // a phone showed the name and the status alone, the counts a swipe away nobody
            // could see, and the last seen and last reception not at all (Tim, 2026-09-30)
            cardOf={(g) => (
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{g.display_name}</span>
                  {isRelay(g) && (
                    <Badge variant="outline">{t("Relay (mesh)")}</Badge>
                  )}
                  {isOffloadStation(g) && (
                    <Badge variant="outline">{t("Offload station")}</Badge>
                  )}
                  <StatusBadge value={g.status} />
                </div>
                <div className="text-xs text-muted-foreground">
                  {g.display_name !== g.external_id && (
                    <span className="mr-2 font-mono">{g.external_id}</span>
                  )}
                  {g.data_source_name}
                  {" · "}
                  {t("seen {{ago}}", { ago: formatAgo(g.last_seen_at) })}
                </div>
                <div className="text-xs">
                  {g.receptions > 0
                    ? t(
                        "{{receptions}} receptions from {{devices}} devices in the last 30 days",
                        { receptions: g.receptions, devices: g.devices },
                      )
                    : t(
                        "Heard none of the project's devices in the last 30 days",
                      )}
                  {signal(g.mean_rssi, g.mean_snr) &&
                    ` · ${signal(g.mean_rssi, g.mean_snr)}`}
                </div>
                <div className="text-xs">
                  {g.last_reception_at
                    ? t("Last reception {{ago}}", {
                        ago: formatAgo(g.last_reception_at),
                      })
                    : t("No reception in 30 days")}
                  {coords(g) && (
                    <span className="ml-2 font-mono text-muted-foreground">
                      {coords(g)}
                    </span>
                  )}
                </div>
              </div>
            )}
            searchable
            isLoading={gateways.isPending}
            emptyMessage={t(
              "No gateway known for this project's data sources yet. Gateways appear from the receptions a network reports and from the platform's gateway list, read every day and on Sync gateways under Server admin, Data sources.",
            )}
            onRowClick={(g) =>
              void navigate(`/projects/${projectId}/network/gateways/${g.id}`)
            }
            footer={
              shown &&
              (silent > 0
                ? t(
                    "{{count}} gateways, busiest first; {{silent}} heard none of the project's devices in the last 30 days",
                    { count: shown.length, silent },
                  )
                : t("{{count}} gateways, busiest first", {
                    count: shown.length,
                  }))
            }
          />
        ) : (
          <DataTable
            columns={deviceColumns}
            cardOf={(d) => (
              <div className="space-y-1">
                <a
                  className="font-medium underline"
                  href={`/projects/${projectId}/devices/${d.device_id}?tab=traffic`}
                  onClick={(e) => e.stopPropagation()}
                >
                  {d.device_name ?? d.device_id}
                </a>
                <div className="text-xs">
                  <span
                    className={d.gateway_count < 2 ? "text-destructive" : ""}
                  >
                    {t("{{count}} gateways", { count: d.gateway_count })}
                  </span>
                  {" · "}
                  {t("{{count}} uplinks", { count: d.uplinks })}
                  {signal(d.mean_rssi, d.mean_snr) &&
                    ` · ${signal(d.mean_rssi, d.mean_snr)}`}
                </div>
                <div className="text-xs text-muted-foreground">
                  {d.best_gateway_name}
                  {d.best_gateway_share != null &&
                    ` (${Math.round(d.best_gateway_share * 100)} ${t("% of uplinks")})`}
                  {" · "}
                  {t("Last reception {{ago}}", {
                    ago: formatAgo(d.last_reception_at),
                  })}
                </div>
              </div>
            )}
            data={connectivity.data}
            searchable
            isLoading={connectivity.isPending}
            emptyMessage={t("No receptions in the last 30 days.")}
            footer={
              connectivity.data &&
              `${connectivity.data.length} devices, least covered first`
            }
          />
        )}
      </Page>
    </>
  );
}
