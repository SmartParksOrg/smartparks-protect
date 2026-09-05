import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Alert, EventDetail, EventItem, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProjectStream } from "@/hooks/useProjectStream";
import { formatTime } from "@/lib/format";
import { eventIcon, type Scope, scopeBase, SEVERITIES } from "@/lib/rules";

/** Acknowledge and resolve buttons with an optional note, shared by the event detail and the alert inbox. */
export function AlertActions({ scope, alert, onDone }: { scope: Scope; alert: Alert; onDone?: () => void }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const client = useQueryClient();
  const act = useMutationToast({
    mutationFn: ({ action }: { action: "acknowledge" | "resolve" }) => api.post<Alert>(`${scopeBase(scope)}/alerts/${alert.id}/${action}`, { body: { note: note || null } }),
    success: (a) => `Alert ${a.status}`,
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["alerts", scope] }); void client.invalidateQueries({ queryKey: ["events", scope] }); onDone?.(); },
  });
  if (alert.status === "resolved") return <div className="text-sm text-muted-foreground">{t("Resolved")} {formatTime(alert.resolved_at)}{alert.note ? `: ${alert.note}` : ""}</div>;
  return (
    <div className="space-y-2">
      <Textarea rows={2} placeholder={t("Note (optional)")} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex gap-2">
        {alert.status === "open" && <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => act.mutate({ action: "acknowledge" })}>{t("Acknowledge")}</Button>}
        <Button size="sm" disabled={act.isPending} onClick={() => act.mutate({ action: "resolve" })}>{t("Resolve")}</Button>
      </div>
    </div>
  );
}

/** Detail of one event: context, alert with actions, deliveries of the automations. */
export function EventDetailDialog({ scope, eventId, onClose }: { scope: Scope; eventId: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const detail = useQuery({ queryKey: queryKeys.event(scope, eventId ?? ""), queryFn: () => api.get<EventDetail>(`${scopeBase(scope)}/events/${eventId}`), enabled: Boolean(eventId) });
  const d = detail.data;
  const projectPath = scope === "server" ? null : `/projects/${scope}`;
  return (
    <Dialog open={eventId !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">{d && <Icon iconKey={eventIcon(d.event.event_type)} className="size-5 text-primary" />}{d?.event.title ?? "Event"}</DialogTitle>
          <DialogDescription>{d ? `${d.event.event_type} at ${formatTime(d.event.time)}` : "Loading…"}</DialogDescription>
        </DialogHeader>
        {detail.error && <Callout kind="error">{detail.error.message}</Callout>}
        {d && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div><span className="text-muted-foreground">{t("Severity")}</span><div><StatusBadge value={d.event.severity} /></div></div>
              <div><span className="text-muted-foreground">{t("Created")}</span><div>{formatTime(d.event.created_at)}</div></div>
              {d.event.entity_id && projectPath && <div><span className="text-muted-foreground">{t("Entity")}</span><div><Link className="underline" to={`${projectPath}/map?entity=${d.event.entity_id}`}>{t("show on map")}</Link></div></div>}
              {d.event.device_id && projectPath && <div><span className="text-muted-foreground">{t("Device")}</span><div><Link className="underline" to={`${projectPath}/devices/${d.event.device_id}`}>{t("open device")}</Link></div></div>}
              {d.event.trace_id && projectPath && <div><span className="text-muted-foreground">{t("Trace")}</span><div><Link className="underline" to={`${projectPath}/network/traces?trace=${d.event.trace_id}`}>{t("view processing trace")}</Link></div></div>}
              {d.event.description && <div className="col-span-2"><span className="text-muted-foreground">{t("Description")}</span><div>{d.event.description}</div></div>}
            </div>
            {d.alert && (
              <div className="rounded-md border p-3">
                <div className="mb-2 flex items-center gap-2 font-medium">{t("Alert")} <StatusBadge value={d.alert.status} /></div>
                <AlertActions scope={scope} alert={d.alert} onDone={() => void detail.refetch()} />
              </div>
            )}
            <div>
              <div className="mb-1 font-medium">{t("Deliveries")}</div>
              {d.deliveries.length === 0 ? <div className="text-muted-foreground">{t("No automation acted on this event.")}</div> : (
                <ul className="space-y-1">{d.deliveries.map((x) => <li key={x.id} className="flex flex-wrap items-center gap-2"><StatusBadge value={x.status} /><span>{x.action_type}</span><span className="text-xs text-muted-foreground">{x.attempts} {t("attempt")}{x.attempts === 1 ? "" : "s"}{x.delivered_at ? `, delivered ${formatTime(x.delivered_at)}` : ""}</span>{x.error_message && <span className="text-xs text-destructive">{x.error_message}</span>}</li>)}</ul>
              )}
            </div>
            <div><div className="mb-1 font-medium">{t("Context")}</div><JsonView value={d.event.context} /></div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Events of a project newest first, with filters and a time cursor; the detail opens from `?event=`. */
export function EventsPage({ scope: scopeProp }: { scope?: Scope } = {}) {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const scope = scopeProp ?? projectId;
  const [params, setParams] = useSearchParams();
  const eventType = params.get("type") ?? "";
  const severity = params.get("severity") ?? "";
  const selected = params.get("event");
  const [cursor, setCursor] = useState<string | null>(null);
  const [pages, setPages] = useState<EventItem[]>([]);
  const query = { event_type: eventType || undefined, severity: severity || undefined, limit: 100, cursor: cursor ?? undefined };
  const events = useQuery({ queryKey: queryKeys.events(scope, query), queryFn: () => api.get<PageType<EventItem>>(`${scopeBase(scope)}/events`, { query }) });
  const client = useQueryClient();
  useProjectStream(scope === "server" ? undefined : scope, (m) => { if (m.topic === "event.created") void client.invalidateQueries({ queryKey: ["events", scope] }); });
  const items = [...pages, ...(events.data?.items ?? [])];

  const columns: ColumnDef<EventItem, unknown>[] = [
    { header: t("Time"), accessorKey: "time", cell: ({ getValue }) => <span className="whitespace-nowrap">{formatTime(getValue<string>())}</span> },
    { header: t("Event"), accessorKey: "title", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={eventIcon(row.original.event_type)} className="size-4 text-primary" />{row.original.title}</span> },
    { header: t("Type"), accessorKey: "event_type", cell: ({ getValue }) => <code className="text-xs">{getValue<string>()}</code> },
    { header: t("Severity"), accessorKey: "severity", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Alert"), accessorKey: "alert_status", cell: ({ getValue }) => <StatusBadge value={getValue<string | null>()} /> },
  ];

  return (
    <>
      <PageHeader title={scope === "server" ? "System events" : "Events"} description={t("Facts produced by rules, devices and integrations. An alert is an event that needs a person.")} actions={<Button variant="outline" size="icon" aria-label={t("Refresh")} onClick={() => { setPages([]); setCursor(null); void events.refetch(); }}><RefreshCw className="size-4" /></Button>} />
      <Page>
        <div className="flex flex-wrap items-end gap-2">
          <Input className="w-48" placeholder={t("Event type, e.g. GEOFENCE_EXIT")} aria-label={t("Event type")} value={eventType} onChange={(e) => { setPages([]); setCursor(null); setParams((p) => { if (e.target.value) p.set("type", e.target.value.toUpperCase()); else p.delete("type"); return p; }, { replace: true }); }} />
          <Select value={severity || "all"} onValueChange={(v) => { setPages([]); setCursor(null); setParams((p) => { if (v === "all") p.delete("severity"); else p.set("severity", v); return p; }, { replace: true }); }}>
            <SelectTrigger className="w-36" aria-label={t("Severity")}><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">{t("Any severity")}</SelectItem>{SEVERITIES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        {events.error && <Callout kind="error">{events.error.message}</Callout>}
        <DataTable columns={columns} data={items} searchable isLoading={events.isPending && pages.length === 0} emptyMessage={t("No events yet. Enable a rule, or wait for a device event.")} onRowClick={(e) => setParams((p) => { p.set("event", e.id); return p; }, { replace: true })} footer={events.data?.next_cursor ? <Button variant="outline" size="sm" onClick={() => { setPages(items); setCursor(events.data?.next_cursor ?? null); }}>{t("Load older")}</Button> : `${items.length} events`} />
      </Page>
      <EventDetailDialog scope={scope} eventId={selected} onClose={() => setParams((p) => { p.delete("event"); return p; }, { replace: true })} />
    </>
  );
}
