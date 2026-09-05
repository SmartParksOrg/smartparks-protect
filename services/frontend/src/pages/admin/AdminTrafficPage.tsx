import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AdminCommand, AdminDelivery, AdminDeliveryDetail, DataSource, Page as PageType, TrafficRow, TrafficSummary } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { CommandDetailDialog } from "@/components/control/DeviceControl";
import { DataTable } from "@/components/data/DataTable";
import { SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const EVENT_TYPES = ["uplink", "join", "status", "downlink_ack", "downlink_transmitted", "log", "location", "gateway_receptions"];
const DELIVERY_STATUSES = ["queued", "sent", "failed", "skipped"];
const COMMAND_STATUSES = ["queued", "transmitted", "acknowledged", "confirmed_by_device", "failed", "expired"];
type Tab = "inbound" | "outbound" | "commands";

/** Server admin, Traffic: what the server receives, delivers and sends to devices, side by side
 * (architecture 8.3 and 26). Three lists, not one merged stream: the rows mean different things. */
export function AdminTrafficPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "outbound" ? "outbound" : params.get("tab") === "commands" ? "commands" : "inbound";
  const set = (key: string, value: string) => setParams((p) => { if (value) p.set(key, value); else p.delete(key); return p; }, { replace: true });
  const summary = useQuery({ queryKey: queryKeys.adminTrafficSummary, queryFn: () => api.get<TrafficSummary>("/api/v1/admin/traffic/summary"), refetchInterval: 15_000 });
  return (
    <>
      <PageHeader
        title={t("Traffic")}
        description={t("Everything the server receives from platforms, delivers to partners and sends to devices, across every project")}
        actions={<Tabs value={tab} onValueChange={(v) => set("tab", v)}><TabsList><TabsTrigger value="inbound">{t("Inbound")}</TabsTrigger><TabsTrigger value="outbound">{t("Outbound")}</TabsTrigger><TabsTrigger value="commands">{t("Commands")}</TabsTrigger></TabsList></Tabs>}
      />
      <Page>
        {summary.data && (
          <div className="flex flex-wrap gap-2 text-xs">
            <Chip label={t("received last hour")} value={summary.data.inbound_events} tone={summary.data.inbound_failed ? "warn" : "ok"} />
            {summary.data.inbound_failed > 0 && <Chip label={t("failed to process")} value={summary.data.inbound_failed} tone="bad" />}
            {summary.data.inbound_unassigned > 0 && <Chip label={t("from unknown devices")} value={summary.data.inbound_unassigned} tone="warn" />}
            {Object.entries(summary.data.outbound_by_status ?? {}).map(([status, count]) => <Chip key={status} label={t("deliveries {{status}}", { status })} value={count} tone={status === "failed" ? "bad" : "ok"} />)}
            {Object.entries(summary.data.commands_by_status ?? {}).map(([status, count]) => <Chip key={status} label={t("commands {{status}}", { status: status.replaceAll("_", " ") })} value={count} tone={status === "failed" ? "bad" : "ok"} />)}
          </div>
        )}
        {tab === "inbound" && <InboundTab params={params} set={set} />}
        {tab === "outbound" && <OutboundTab params={params} set={set} />}
        {tab === "commands" && <CommandsTab params={params} set={set} />}
      </Page>
    </>
  );
}

function Chip({ label, value, tone }: { label: string; value: number; tone: "ok" | "warn" | "bad" }) {
  const cls = tone === "bad" ? "border-destructive/40 bg-destructive/10 text-destructive" : tone === "warn" ? "border-brand-sand/50 bg-brand-sand/10" : "bg-muted";
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ${cls}`}><span className="font-medium tabular-nums">{value}</span> {label}</span>;
}

type TabProps = { params: URLSearchParams; set: (key: string, value: string) => void };

function InboundTab({ params, set }: TabProps) {
  const { t } = useTranslation();
  const sourceId = params.get("source") ?? "";
  const eventType = params.get("type") ?? "";
  const identity = params.get("identity") ?? "";
  const hours = Number(params.get("hours") ?? 24);
  const [selected, setSelected] = useState<{ id: number; ingestedAt: string } | null>(null);
  const sources = useQuery({ queryKey: queryKeys.dataSources, queryFn: () => api.get<PageType<DataSource>>("/api/v1/data-sources", { query: { limit: 200 } }) });
  const query = { data_source_id: sourceId || undefined, event_type: eventType || undefined, external_id: identity || undefined, hours, limit: 200 };
  const traffic = useQuery({ queryKey: queryKeys.adminTraffic("inbound", query), queryFn: () => api.get<TrafficRow[]>("/api/v1/admin/traffic/inbound", { query: { ...query, hours: undefined, from: new Date(Date.now() - hours * 3600_000).toISOString() } }), refetchInterval: 5_000 });
  const columns: ColumnDef<TrafficRow, unknown>[] = [
    { header: t("Received"), accessorKey: "ingested_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Source"), accessorKey: "data_source_name" },
    { header: t("Identity"), accessorKey: "external_id", cell: ({ row }) => <span className="font-mono text-xs">{row.original.external_id ?? ""}</span> },
    { header: t("Device"), accessorKey: "device_name", cell: ({ row }) => row.original.device_name ?? <span className="text-muted-foreground">{t("not linked")}</span> },
    { header: t("Type"), accessorKey: "event_type" },
    { header: t("Port"), accessorKey: "f_port" },
    { header: t("RSSI"), accessorKey: "best_rssi", cell: ({ getValue }) => getValue<number | null>()?.toFixed(0) ?? "" },
    { header: t("Gateways"), accessorKey: "gateway_count" },
    { header: t("Status"), accessorKey: "processing_status", cell: ({ row }) => <span className="inline-flex items-center gap-1"><StatusBadge value={row.original.processing_status} />{row.original.error_code && <span className="text-xs text-destructive">{row.original.error_code}</span>}</span> },
  ];
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={sourceId || "all"} onValueChange={(v) => set("source", v === "all" ? "" : v)}>
          <SelectTrigger className="w-56" aria-label={t("Data source")}><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">{t("All data sources")}</SelectItem>{sources.data?.items.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
        </Select>
        <Input className="w-44 font-mono" placeholder={t("Identity contains")} value={identity} onChange={(e) => set("identity", e.target.value)} aria-label={t("Identity filter")} />
        <Select value={eventType || "all"} onValueChange={(v) => set("type", v === "all" ? "" : v)}>
          <SelectTrigger className="w-44"><SelectValue placeholder={t("All types")} /></SelectTrigger>
          <SelectContent><SelectItem value="all">{t("All types")}</SelectItem>{EVENT_TYPES.map((type) => <SelectItem key={type} value={type}>{type}</SelectItem>)}</SelectContent>
        </Select>
        <Input type="number" min={1} max={720} className="w-24" value={hours} onChange={(e) => set("hours", e.target.value)} aria-label={t("Hours back")} />
        <Button variant="outline" size="icon" onClick={() => traffic.refetch()} aria-label={t("Refresh")}><RefreshCw className="size-4" /></Button>
      </div>
      {traffic.error && <Callout kind="error">{traffic.error.message}</Callout>}
      <DataTable columns={columns} data={traffic.data} searchable isLoading={traffic.isPending} emptyMessage={t("Nothing received in this window.")} onRowClick={(r) => setSelected({ id: r.source_event_id, ingestedAt: r.ingested_at })} footer={traffic.data && t("{{count}} messages, last {{hours}} hours", { count: traffic.data.length, hours })} />
      <SourceEventDialog id={selected?.id ?? null} ingestedAt={selected?.ingestedAt ?? null} onClose={() => setSelected(null)} />
    </>
  );
}

function OutboundTab({ params, set }: TabProps) {
  const { t } = useTranslation();
  const status = params.get("status") ?? "";
  const stale = params.get("stale") === "1";
  const [detail, setDetail] = useState<AdminDelivery | null>(null);
  const query = { status: status || undefined, stale: stale || undefined, limit: 200 };
  const deliveries = useQuery({ queryKey: queryKeys.adminTraffic("outbound", query), queryFn: () => api.get<PageType<AdminDelivery>>("/api/v1/admin/traffic/outbound", { query }), refetchInterval: 10_000 });
  const full = useQuery({ queryKey: queryKeys.adminDelivery(detail?.id ?? ""), queryFn: () => api.get<AdminDeliveryDetail>(`/api/v1/admin/traffic/outbound/${detail?.id}`), enabled: detail !== null });
  const retry = useMutationToast({ mutationFn: (d: AdminDelivery) => api.post<AdminDelivery>(`/api/v1/projects/${d.project_id}/integrations/deliveries/${d.id}/retry`), invalidate: [queryKeys.adminTraffic("outbound", query)], success: t("Queued again"), onSuccess: () => setDetail(null) });
  const resend = useMutationToast({ mutationFn: (d: AdminDelivery) => api.post<AdminDelivery>(`/api/v1/projects/${d.project_id}/integrations/deliveries/${d.id}/resend`), invalidate: [queryKeys.adminTraffic("outbound", query)], success: t("Corrected object queued for delivery"), onSuccess: () => setDetail(null) });
  const columns: ColumnDef<AdminDelivery, unknown>[] = [
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Project"), accessorKey: "project_name" },
    { header: t("Integration"), accessorKey: "integration_name", cell: ({ row }) => <span>{row.original.integration_name ?? ""} <span className="text-xs text-muted-foreground">{row.original.connector_key ?? ""}</span></span> },
    { header: t("Object"), id: "object", cell: ({ row }) => <span className="text-xs">{row.original.object_type} {row.original.object_type === "event" ? row.original.object_id.slice(0, 8) : row.original.object_id}<span className="text-muted-foreground"> {t("at {{time}}", { time: formatTime(row.original.object_time) })}</span></span> },
    { header: t("Origin"), accessorKey: "origin" },
    { header: t("Status"), accessorKey: "status", cell: ({ row }) => <span className="inline-flex items-center gap-1"><StatusBadge value={row.original.status} />{row.original.stale_at && <span className="text-xs text-brand-sand">{t("stale")}</span>}</span> },
    { header: t("Attempts"), accessorKey: "attempts" },
    { header: t("Detail"), accessorKey: "error_message", cell: ({ getValue }) => <span className="text-xs text-destructive">{getValue<string | null>() ?? ""}</span> },
  ];
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={status || "all"} onValueChange={(v) => set("status", v === "all" ? "" : v)}>
          <SelectTrigger className="w-44" aria-label={t("Status")}><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">{t("Any status")}</SelectItem>{DELIVERY_STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
        </Select>
        <Button variant={stale ? "default" : "outline"} size="sm" onClick={() => set("stale", stale ? "" : "1")}>{t("Stale only")}</Button>
        <Button variant="outline" size="icon" onClick={() => deliveries.refetch()} aria-label={t("Refresh")}><RefreshCw className="size-4" /></Button>
      </div>
      {deliveries.error && <Callout kind="error">{deliveries.error.message}</Callout>}
      <DataTable columns={columns} data={deliveries.data?.items} searchable isLoading={deliveries.isPending} emptyMessage={t("No deliveries in this view.")} onRowClick={(d) => setDetail(d)} footer={deliveries.data && t("{{count}} deliveries, newest first", { count: deliveries.data.items.length })} />
      <Dialog open={detail !== null} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>{t("Delivery of {{type}} {{id}}", { type: detail?.object_type, id: detail?.object_type === "event" ? detail?.object_id.slice(0, 8) : detail?.object_id })}</DialogTitle><DialogDescription>{detail && t("{{integration}} in {{project}}, {{origin}}, {{count}} attempts", { integration: detail.integration_name, project: detail.project_name, origin: detail.origin, count: detail.attempts })}</DialogDescription></DialogHeader>
          {detail && (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge value={detail.status} />{detail.delivered_at && <span className="text-xs text-muted-foreground">{t("delivered {{time}}", { time: formatTime(detail.delivered_at) })}</span>}{detail.external_id && <span className="text-xs">{t("target ref {{ref}}", { ref: detail.external_id })}</span>}</div>
              {detail.error_message && <Callout kind={detail.status === "failed" ? "error" : "warning"}>{detail.error_message}</Callout>}
              {detail.stale_at && <Callout kind="warning">{t("The object was corrected after this delivery ({{reason}}, {{time}}). Resend delivers the corrected version as a new delivery.", { reason: detail.stale_reason, time: formatTime(detail.stale_at) })}</Callout>}
              <div><div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{t("Request")}</div><JsonView value={full.data?.request ?? null} /></div>
              <div><div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{t("Response")}</div><JsonView value={full.data?.response ?? {}} /></div>
            </div>
          )}
          <DialogFooter><Button variant="outline" onClick={() => setDetail(null)}>{t("Close")}</Button>{detail && detail.status !== "sent" && <Button onClick={() => retry.mutate(detail)} disabled={retry.isPending}><RotateCcw className="size-4" /> {t("Retry now")}</Button>}{detail?.stale_at && <Button onClick={() => resend.mutate(detail)} disabled={resend.isPending}>{t("Resend corrected")}</Button>}</DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function CommandsTab({ params, set }: TabProps) {
  const { t } = useTranslation();
  const status = params.get("status") ?? "";
  const selected = params.get("command");
  const query = { status: status || undefined, limit: 200 };
  const commands = useQuery({ queryKey: queryKeys.adminTraffic("commands", query), queryFn: () => api.get<PageType<AdminCommand>>("/api/v1/admin/traffic/commands", { query }), refetchInterval: 10_000 });
  const columns: ColumnDef<AdminCommand, unknown>[] = [
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => <span className="whitespace-nowrap">{formatTime(getValue<string>())}</span> },
    { header: t("Project"), accessorKey: "project_name" },
    { header: t("Action"), accessorKey: "action_key" },
    { header: t("Device"), accessorKey: "device_name", cell: ({ row }) => <span>{row.original.device_name ?? ""} <span className="font-mono text-xs text-muted-foreground">{row.original.external_id ?? ""}</span></span> },
    { header: t("Route"), accessorKey: "route" },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("By"), accessorFn: (c) => String(c.actor.kind ?? "") },
    { header: t("Detail"), accessorKey: "error_message", cell: ({ getValue }) => <span className="text-xs text-destructive">{getValue<string | null>() ?? ""}</span> },
  ];
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={status || "all"} onValueChange={(v) => set("status", v === "all" ? "" : v)}>
          <SelectTrigger className="w-48" aria-label={t("Status")}><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">{t("Any status")}</SelectItem>{COMMAND_STATUSES.map((s) => <SelectItem key={s} value={s}>{s.replaceAll("_", " ")}</SelectItem>)}</SelectContent>
        </Select>
        <Button variant="outline" size="icon" onClick={() => commands.refetch()} aria-label={t("Refresh")}><RefreshCw className="size-4" /></Button>
      </div>
      {commands.error && <Callout kind="error">{commands.error.message}</Callout>}
      <DataTable columns={columns} data={commands.data?.items} searchable isLoading={commands.isPending} emptyMessage={t("No commands in this view.")} onRowClick={(c) => set("command", c.id)} footer={commands.data && t("{{count}} commands, newest first", { count: commands.data.items.length })} />
      <CommandDetailDialog commandId={selected} onClose={() => set("command", "")} />
    </>
  );
}
