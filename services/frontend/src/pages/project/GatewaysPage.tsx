import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceConnectivity, Gateway, GatewayDetail } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatAgo, formatTime } from "@/lib/format";

const WINDOWS = [{ hours: 1, label: i18n.t("Last hour") }, { hours: 24, label: i18n.t("Last 24 hours") }, { hours: 168, label: i18n.t("Last 7 days") }, { hours: 720, label: i18n.t("Last 30 days") }];

const coords = (g: Gateway) => { const c = (g.geometry as { coordinates?: number[] } | null)?.coordinates; return c ? `${c[1].toFixed(4)}, ${c[0].toFixed(4)}` : ""; };
const signal = (rssi: number | null | undefined, snr: number | null | undefined) => (rssi == null && snr == null ? "" : `${rssi ?? "?"} dBm / ${snr ?? "?"} dB`);

/** Gateways and connectivity health (architecture 20): which gateways hear the project's devices, and how well each device is covered. */
export function GatewaysPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "connectivity" ? "connectivity" : "gateways";
  const hours = Number(params.get("hours") ?? 24) || 24;
  const base = `/api/v1/projects/${projectId}`;
  const gateways = useQuery({ queryKey: queryKeys.gateways(projectId, hours), queryFn: () => api.get<Gateway[]>(`${base}/gateways`, { query: { hours, limit: 500 } }), refetchInterval: 30_000 });
  const connectivity = useQuery({ queryKey: queryKeys.connectivity(projectId, hours), queryFn: () => api.get<DeviceConnectivity[]>(`${base}/connectivity`, { query: { hours, limit: 500 } }), enabled: tab === "connectivity", refetchInterval: 30_000 });
  const [selected, setSelected] = useState<Gateway | null>(null);
  const detail = useQuery({ queryKey: queryKeys.gateway(projectId, selected?.id ?? "", hours), queryFn: () => api.get<GatewayDetail>(`${base}/gateways/${selected?.id}`, { query: { hours } }), enabled: selected !== null });

  const columns: ColumnDef<Gateway, unknown>[] = [
    { header: t("Gateway"), accessorKey: "display_name", cell: ({ row }) => <span><span className="font-medium">{row.original.display_name}</span>{row.original.display_name !== row.original.external_id && <span className="ml-2 font-mono text-xs text-muted-foreground">{row.original.external_id}</span>}</span> },
    { header: t("State"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Source"), accessorKey: "data_source_name" },
    { header: t("Receptions"), accessorKey: "receptions" },
    { header: t("Devices"), accessorKey: "devices" },
    { header: t("Mean signal"), id: "signal", cell: ({ row }) => signal(row.original.mean_rssi, row.original.mean_snr) },
    { header: t("Last reception"), accessorKey: "last_reception_at", cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
    { header: t("Location"), id: "location", cell: ({ row }) => <span className="font-mono text-xs">{coords(row.original)}</span> },
  ];
  const deviceColumns: ColumnDef<DeviceConnectivity, unknown>[] = [
    { header: t("Device"), accessorKey: "device_name", cell: ({ row }) => <a className="underline" href={`/projects/${projectId}/devices/${row.original.device_id}`} onClick={(e) => e.stopPropagation()}>{row.original.device_name ?? row.original.device_id}</a> },
    { header: t("Gateways"), accessorKey: "gateway_count", cell: ({ row }) => <span className={row.original.gateway_count < 2 ? "text-destructive" : ""}>{row.original.gateway_count}</span> },
    { header: t("Uplinks"), accessorKey: "uplinks" },
    { header: t("Best gateway"), id: "best", cell: ({ row }) => <span>{row.original.best_gateway_name}{row.original.best_gateway_share != null && <span className="ml-1 text-xs text-muted-foreground">{Math.round(row.original.best_gateway_share * 100)} {t("% of uplinks")}</span>}</span> },
    { header: t("Mean signal"), id: "signal", cell: ({ row }) => signal(row.original.mean_rssi, row.original.mean_snr) },
    { header: t("Last reception"), accessorKey: "last_reception_at", cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
  ];

  return (
    <>
      <PageHeader title={t("Gateways")} description={t("Which gateways hear this project's devices, and how well every device is covered. Network health is not device health: a device can be healthy but poorly connected.")} />
      <Page>
        <div className="flex flex-wrap items-center gap-3">
          <Tabs value={tab} onValueChange={(v) => setParams((p) => { p.set("tab", v); return p; }, { replace: true })}><TabsList><TabsTrigger value="gateways">{t("Gateways")}</TabsTrigger><TabsTrigger value="connectivity">{t("Device connectivity")}</TabsTrigger></TabsList></Tabs>
          <Select value={String(hours)} onValueChange={(v) => setParams((p) => { p.set("hours", v); return p; }, { replace: true })}>
            <SelectTrigger className="w-40" aria-label={t("Window")}><SelectValue /></SelectTrigger>
            <SelectContent>{WINDOWS.map((w) => <SelectItem key={w.hours} value={String(w.hours)}>{w.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        {(gateways.error ?? connectivity.error) && <Callout kind="error">{(gateways.error ?? connectivity.error)?.message}</Callout>}
        {tab === "gateways" ? (
          <DataTable columns={columns} data={gateways.data} searchable isLoading={gateways.isPending} emptyMessage={t("No gateway received this project's devices in the window. Gateways appear from the receptions a network reports; the platform's gateway list can be synced under Server admin, Data sources.")} onRowClick={(g) => setSelected(g)} footer={gateways.data && `${gateways.data.length} gateways, busiest first`} />
        ) : (
          <DataTable columns={deviceColumns} data={connectivity.data} searchable isLoading={connectivity.isPending} emptyMessage={t("No receptions in the window.")} footer={connectivity.data && `${connectivity.data.length} devices, least covered first`} />
        )}
      </Page>
      <Dialog open={selected !== null} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader><DialogTitle>{selected?.display_name}</DialogTitle><DialogDescription>{selected && `${selected.data_source_name ?? ""}, gateway ${selected.external_id}`}</DialogDescription></DialogHeader>
          {selected && (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge value={selected.status} /><span className="text-xs text-muted-foreground">{t("seen {{ago}}, first {{first}}", { ago: formatAgo(selected.last_seen_at), first: formatTime(selected.first_seen_at) })}</span></div>
              {coords(selected) && <div className="font-mono text-xs">{coords(selected)}{selected.altitude_m != null ? `, ${selected.altitude_m} m` : ""}</div>}
              {selected.description && <div>{selected.description}</div>}
              {(selected.links ?? []).length > 0 && <div className="flex flex-wrap gap-2">{(selected.links ?? []).map((l) => <Button key={l.key} asChild variant="outline" size="sm"><a href={l.url} target="_blank" rel="noreferrer">{l.label}</a></Button>)}</div>}
              {Object.keys(selected.stats).length > 0 && <div><div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{t("Statistics")} {selected.last_stats_at ? formatAgo(selected.last_stats_at) : ""}</div><JsonView value={selected.stats} /></div>}
              <div>
                <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{t("Devices heard in the window")}</div>
                {detail.data ? (
                  <table className="w-full text-xs"><thead><tr className="text-left text-muted-foreground"><th className="py-1">{t("Device")}</th><th>{t("Receptions")}</th><th>{t("Mean signal")}</th><th>{t("Last")}</th></tr></thead><tbody>{detail.data.devices.map((d) => <tr key={d.device_id ?? "none"} className="border-t"><td className="py-1">{d.device_name ?? d.device_id ?? "unknown"}</td><td>{d.receptions}</td><td>{signal(d.mean_rssi, d.mean_snr)}</td><td>{formatAgo(d.last_reception_at)}</td></tr>)}</tbody></table>
                ) : <span className="text-muted-foreground">{t("Loading…")}</span>}
              </div>
              {Object.keys(selected.attributes).length > 0 && <div><div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{t("Provider diagnostics")}</div><JsonView value={selected.attributes} /></div>}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
