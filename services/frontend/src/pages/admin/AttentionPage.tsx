import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AttentionSummary, DeadLetter, DeviceType, Page as PageType, ProjectWithRole, SourceEventSummary, UnknownIdentity } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { SourceEventDialog, TraceDialog } from "@/components/devices/ProvenancePanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatAgo, formatTime } from "@/lib/format";

const DEAD_TOPICS = ["source_event.received", "position.created", "measurement.created", "device.state_changed", "event.created", "needs_attention.created"];

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "warn" | "bad" }) {
  return (
    <Card><CardContent className="pt-4"><div className="text-xs text-muted-foreground">{label}</div><div className={`text-2xl font-semibold ${tone === "bad" ? "text-destructive" : tone === "warn" ? "text-brand-sand" : ""}`}>{value}</div></CardContent></Card>
  );
}

function CreateDeviceDialog({ identity, onClose }: { identity: UnknownIdentity | null; onClose: () => void }) {
  const { t } = useTranslation();
  const types = useQuery({ queryKey: queryKeys.deviceTypes, queryFn: () => api.get<PageType<DeviceType>>("/api/v1/device-types", { query: { limit: 500 } }) });
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const [name, setName] = useState("");
  const [typeId, setTypeId] = useState("");
  const [projectId, setProjectId] = useState("");
  const create = useMutationToast({
    mutationFn: () => api.post(`/api/v1/attention/identities/${identity?.id}/create-device`, { body: { name, device_type_id: typeId, project_id: projectId || null, valid_from: identity?.first_seen_at ?? null } }),
    invalidate: [queryKeys.unknownIdentities, queryKeys.attentionSummary, queryKeys.devices({})],
    success: t("Device created; retained events are being processed"),
    onSuccess: onClose,
  });
  return (
    <Dialog open={identity != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t("Create device for")} {identity?.external_id}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <Field label={t("Device name")} htmlFor="new-device-name"><Input id="new-device-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label={t("Device type")} htmlFor="new-device-type">
            <Select value={typeId} onValueChange={setTypeId}><SelectTrigger id="new-device-type"><SelectValue placeholder={t("Choose")} /></SelectTrigger><SelectContent>{types.data?.items.map((t) => <SelectItem key={t.id} value={t.id}>{t.label} ({t.driver_key})</SelectItem>)}</SelectContent></Select>
          </Field>
          <Field label={t("Assign to project")} htmlFor="new-device-project" hint={t("From the first time this identity was seen")}>
            <Select value={projectId || "none"} onValueChange={(v) => setProjectId(v === "none" ? "" : v)}><SelectTrigger id="new-device-project"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{t("No project yet")}</SelectItem>{projects.data?.items.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
          </Field>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>{t("Cancel")}</Button><Button disabled={!name || !typeId || create.isPending} onClick={() => create.mutate()}>{t("Create and reprocess")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function AttentionPage() {
  const { t } = useTranslation();
  const summary = useQuery({ queryKey: queryKeys.attentionSummary, queryFn: () => api.get<AttentionSummary>("/api/v1/attention/summary"), refetchInterval: 30_000 });
  const identities = useQuery({ queryKey: queryKeys.unknownIdentities, queryFn: () => api.get<PageType<UnknownIdentity>>("/api/v1/attention/identities", { query: { limit: 200 } }) });
  const failed = useQuery({ queryKey: queryKeys.failedSourceEvents("failed"), queryFn: () => api.get<SourceEventSummary[]>("/api/v1/attention/source-events", { query: { status: "failed", limit: 200 } }) });
  const [topic, setTopic] = useState(DEAD_TOPICS[0]);
  const dead = useQuery({ queryKey: queryKeys.deadLetters(topic), queryFn: () => api.get<DeadLetter[]>("/api/v1/attention/dead-letters", { query: { topic, limit: 200 } }) });
  const [creating, setCreating] = useState<UnknownIdentity | null>(null);
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(null);
  const [trace, setTrace] = useState<string | null>(null);
  const invalidateAll = [queryKeys.unknownIdentities, queryKeys.attentionSummary, queryKeys.failedSourceEvents("failed"), queryKeys.deadLetters(topic)];
  const ignore = useMutationToast({ mutationFn: (id: string) => api.post(`/api/v1/attention/identities/${id}/ignore`), invalidate: invalidateAll, success: t("Identity ignored") });
  const reprocess = useMutationToast({ mutationFn: (e: SourceEventSummary) => api.post(`/api/v1/attention/source-events/${e.id}/reprocess`, { query: { ingested_at: e.ingested_at } }), invalidate: invalidateAll, success: t("Source event put back on the bus") });
  const retry = useMutationToast({ mutationFn: (d: DeadLetter) => api.post(`/api/v1/attention/dead-letters/${d.topic}/${d.id}/retry`), invalidate: invalidateAll, success: t("Message republished") });
  const resolve = useMutationToast({ mutationFn: (d: DeadLetter) => api.post(`/api/v1/attention/dead-letters/${d.topic}/${d.id}/resolve`), invalidate: invalidateAll, success: t("Dead letter resolved") });

  const identityColumns: ColumnDef<UnknownIdentity, unknown>[] = [
    { header: t("External id"), accessorKey: "external_id", cell: ({ getValue }) => <span className="font-mono">{getValue<string>()}</span> },
    { header: t("Data source"), accessorKey: "data_source_name" },
    { header: t("Type"), accessorKey: "identity_type" },
    { header: t("First seen"), accessorKey: "first_seen_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) },
    { header: t("Last seen"), accessorKey: "last_seen_at", cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
    { header: t("Events"), accessorKey: "event_count" },
    { id: "actions", header: "", cell: ({ row }) => <div className="flex gap-1"><Button size="sm" onClick={() => setCreating(row.original)}>{t("Create device")}</Button><Button size="sm" variant="ghost" onClick={() => ignore.mutate(row.original.id)}>{t("Ignore")}</Button></div> },
  ];
  const failedColumns: ColumnDef<SourceEventSummary, unknown>[] = [
    { header: t("Ingested"), accessorKey: "ingested_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("External id"), accessorKey: "external_id", cell: ({ getValue }) => <span className="font-mono">{getValue<string | null>()}</span> },
    { header: t("Type"), accessorKey: "event_type" },
    { header: t("Error"), accessorKey: "error_code", cell: ({ getValue }) => <span className="text-xs text-destructive">{getValue<string | null>()}</span> },
    { id: "actions", header: "", cell: ({ row }) => <div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setEvent({ id: row.original.id, ingestedAt: row.original.ingested_at })}>{t("Inspect")}</Button>{row.original.trace_id && <Button size="sm" variant="ghost" onClick={() => setTrace(row.original.trace_id)}>{t("Trace")}</Button>}<Button size="sm" variant="ghost" disabled={!row.original.device_id} onClick={() => reprocess.mutate(row.original)}>{t("Reprocess")}</Button></div> },
  ];
  const deadColumns: ColumnDef<DeadLetter, unknown>[] = [
    { header: t("Dead at"), accessorKey: "dead_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) },
    { header: t("Error"), accessorKey: "error_code" },
    { header: t("Message"), accessorKey: "error", cell: ({ getValue }) => <span className="block max-w-md truncate text-xs" title={getValue<string>() ?? ""}>{getValue<string | null>()}</span> },
    { header: t("Attempts"), accessorKey: "delivery_count" },
    { id: "actions", header: "", cell: ({ row }) => <div className="flex gap-1">{row.original.trace_id && <Button size="sm" variant="ghost" onClick={() => setTrace(row.original.trace_id ?? null)}>{t("Trace")}</Button>}<Button size="sm" variant="outline" onClick={() => retry.mutate(row.original)}>{t("Retry")}</Button><Button size="sm" variant="ghost" onClick={() => resolve.mutate(row.original)}>{t("Resolve")}</Button></div> },
  ];
  const s = summary.data;
  return (
    <>
      <PageHeader title={t("Needs attention")} description={t("Unknown devices, failed messages and dead letters, with the actions to fix them")} />
      <Page>
        {s && s.stale_workers.length > 0 && <Callout kind="error">{t("Workers without a heartbeat for 15 minutes: {{workers}}", { workers: s.stale_workers.join(", ") })}</Callout>}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label={t("Unknown identities")} value={s?.unknown_identities ?? "…"} tone={s?.unknown_identities ? "warn" : undefined} />
          <Stat label={t("Unassigned source events")} value={s?.unassigned_source_events ?? "…"} tone={s?.unassigned_source_events ? "warn" : undefined} />
          <Stat label={t("Failed source events")} value={s?.failed_source_events ?? "…"} tone={s?.failed_source_events ? "bad" : undefined} />
          <Stat label={t("Dead letters")} value={s ? Object.values(s.dead_letters).reduce((a, b) => a + b, 0) : "…"} tone={s && Object.keys(s.dead_letters).length ? "bad" : undefined} />
        </div>
        <Tabs defaultValue="identities">
          <TabsList><TabsTrigger value="identities">{t("Unknown identities")}</TabsTrigger><TabsTrigger value="failed">{t("Failed source events")}</TabsTrigger><TabsTrigger value="dead">{t("Dead letters")}</TabsTrigger></TabsList>
          <TabsContent value="identities"><DataTable columns={identityColumns} data={identities.data?.items} isLoading={identities.isPending} emptyMessage={t("Every identity is linked to a device.")} /></TabsContent>
          <TabsContent value="failed"><DataTable columns={failedColumns} data={failed.data} isLoading={failed.isPending} emptyMessage={t("No failed source events.")} /></TabsContent>
          <TabsContent value="dead" className="space-y-3">
            <Select value={topic} onValueChange={setTopic}><SelectTrigger className="w-72"><SelectValue /></SelectTrigger><SelectContent>{DEAD_TOPICS.map((t) => <SelectItem key={t} value={t}>{t} {s?.dead_letters[t] ? `(${s.dead_letters[t]})` : ""}</SelectItem>)}</SelectContent></Select>
            <DataTable columns={deadColumns} data={dead.data} isLoading={dead.isPending} emptyMessage={t("No dead letters on this topic.")} />
          </TabsContent>
        </Tabs>
      </Page>
      <CreateDeviceDialog identity={creating} onClose={() => setCreating(null)} />
      <SourceEventDialog id={event?.id ?? null} ingestedAt={event?.ingestedAt ?? null} onClose={() => setEvent(null)} />
      <TraceDialog traceId={trace} onClose={() => setTrace(null)} />
    </>
  );
}
