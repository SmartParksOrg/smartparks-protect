import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Alert, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useProjectStream } from "@/hooks/useProjectStream";
import { formatAgo, formatTime } from "@/lib/format";
import { eventIcon, type Scope, scopeBase } from "@/lib/rules";
import { AlertActions, EventDetailDialog } from "@/pages/project/EventsPage";

const STATUSES = ["open", "acknowledged", "resolved"] as const;

/** The alert inbox (architecture 16): open, acknowledged and resolved, with the lifecycle actions. */
export function AlertsPage({ scope: scopeProp }: { scope?: Scope } = {}) {
  const { projectId = "" } = useParams();
  const scope = scopeProp ?? projectId;
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "open";
  const selectedEvent = params.get("event");
  const [acting, setActing] = useState<Alert | null>(null);
  const query = { status, limit: 200 };
  const alerts = useQuery({ queryKey: queryKeys.alerts(scope, query), queryFn: () => api.get<PageType<Alert>>(`${scopeBase(scope)}/alerts`, { query }), refetchInterval: 60_000 });
  const client = useQueryClient();
  useProjectStream(scope === "server" ? undefined : scope, (m) => { if (m.topic === "alert.created" || m.topic === "event.created") void client.invalidateQueries({ queryKey: ["alerts", scope] }); });
  const projectPath = scope === "server" ? null : `/projects/${scope}`;

  const columns: ColumnDef<Alert, unknown>[] = [
    { header: "Severity", accessorKey: "severity", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: "Alert", accessorKey: "title", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={eventIcon(row.original.event_type)} className="size-4 text-primary" />{row.original.title}</span> },
    { header: "When", accessorKey: "time", cell: ({ row }) => <span title={formatTime(row.original.time)}>{formatAgo(row.original.time)}</span> },
    { header: "Entity", accessorKey: "entity_id", cell: ({ getValue }) => { const id = getValue<string | null>(); return id && projectPath ? <Link className="underline" to={`${projectPath}/map?entity=${id}`} onClick={(e) => e.stopPropagation()}>on map</Link> : ""; } },
    { header: "Status", accessorKey: "status", cell: ({ row }) => <span className="inline-flex items-center gap-2"><StatusBadge value={row.original.status} />{row.original.status === "acknowledged" && <span className="text-xs text-muted-foreground">{formatAgo(row.original.acknowledged_at)}</span>}</span> },
    { id: "actions", header: "", cell: ({ row }) => row.original.status !== "resolved" && <span onClick={(e) => e.stopPropagation()}><Button size="sm" variant="outline" onClick={() => setActing(row.original)}>{row.original.status === "open" ? "Acknowledge" : "Resolve"}</Button></span> },
  ];

  return (
    <>
      <PageHeader title={scope === "server" ? "System alerts" : "Alerts"} description={scope === "server" ? "Stale workers, dead letters and lag, opened by the system checks and resolved when they clear" : "Events that need a person: acknowledge to take ownership, resolve when done"} />
      <Page>
        <Tabs value={status} onValueChange={(v) => setParams((p) => { p.set("status", v); return p; }, { replace: true })}>
          <TabsList>{STATUSES.map((s) => <TabsTrigger key={s} value={s}>{s}</TabsTrigger>)}</TabsList>
        </Tabs>
        {alerts.error && <Callout kind="error">{alerts.error.message}</Callout>}
        <DataTable columns={columns} data={alerts.data?.items} isLoading={alerts.isPending} emptyMessage={status === "open" ? "No open alerts." : `No ${status} alerts.`} onRowClick={(a) => setParams((p) => { p.set("event", a.event_id); return p; }, { replace: true })} footer={alerts.data && `${alerts.data.items.length} alerts`} />
      </Page>
      <Dialog open={acting !== null} onOpenChange={(o) => !o && setActing(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{acting?.title}</DialogTitle><DialogDescription>{acting?.event_type} at {formatTime(acting?.time)}</DialogDescription></DialogHeader>
          {acting && <AlertActions scope={scope} alert={acting} onDone={() => setActing(null)} />}
        </DialogContent>
      </Dialog>
      <EventDetailDialog scope={scope} eventId={selectedEvent} onClose={() => setParams((p) => { p.delete("event"); return p; }, { replace: true })} />
    </>
  );
}

export function AdminAlertsPage() {
  return <AlertsPage scope="server" />;
}
