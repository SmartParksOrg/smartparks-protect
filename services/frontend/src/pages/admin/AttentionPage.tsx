import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AttentionSummary, BulkCreateResult, BulkIgnoreResult, ClockAheadDevice, DeadLetter, DeviceType, EntityType, NewMetric, NewMetricsResponse, Page as PageType, ProjectWithRole, SourceEventSummary, UnknownIdentity } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { SourceEventDialog, TraceDialog } from "@/components/devices/ProvenancePanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatAgo, formatTime } from "@/lib/format";
import { useQueryClient } from "@tanstack/react-query";

const DEAD_TOPICS = ["source_event.received", "position.created", "measurement.created", "device.state_changed", "event.created", "needs_attention.created"];

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "warn" | "bad" }) {
  return (
    <Card><CardContent className="pt-4"><div className="text-xs text-muted-foreground">{label}</div><div className={`text-2xl font-semibold ${tone === "bad" ? "text-destructive" : tone === "warn" ? "text-brand-sand" : ""}`}>{value}</div></CardContent></Card>
  );
}

/** How far the decoder is with the events that wait for it (decision D121): the queue drains as
 * it works, so the page polls the summary every few seconds while any wait, and the bar runs
 * from the most events seen waiting since it was last empty. */
function QueueProgress({ queued, onDrained }: { queued: number; onDrained: () => void }) {
  const { t } = useTranslation();
  // The most events seen waiting since the queue was last empty, adjusted during render.
  const [peak, setPeak] = useState(0);
  if (queued > peak) setPeak(queued);
  if (queued === 0 && peak > 0) setPeak(0);
  // The drain is announced once, from the count the effect kept.
  const counted = useRef(0);
  useEffect(() => {
    if (queued > 0) {
      counted.current = Math.max(counted.current, queued);
      return;
    }
    if (counted.current > 0) {
      toast.success(t("{{count}} retained events processed", { count: counted.current }));
      counted.current = 0;
      onDrained();
    }
  }, [queued, onDrained, t]);
  if (queued === 0) return null;
  const total = Math.max(peak, queued);
  const done = total - queued;
  return (
    <Card>
      <CardContent className="space-y-2 pt-4">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">{t("Processing retained events")}</span>
          <span className="text-muted-foreground">{t("{{done}} of {{total}} done, {{queued}} waiting", { done, total, queued })}</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label={t("Processing retained events")}>
          <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${total ? Math.round((done / total) * 100) : 0}%` }} />
        </div>
        <p className="text-xs text-muted-foreground">{t("The decoder works through them in the background; the counts, the devices and the map fill in as it goes. You can leave this page.")}</p>
      </CardContent>
    </Card>
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

/** The name the platform knows an identity by, or its external id: what a bulk create names the device. */
const platformName = (identity: UnknownIdentity) => (typeof identity.attributes?.name === "string" && identity.attributes.name.trim()) || identity.external_id;

function BulkCreateDialog({ identities, onClose, onDone }: { identities: UnknownIdentity[]; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const types = useQuery({ queryKey: queryKeys.deviceTypes, queryFn: () => api.get<PageType<DeviceType>>("/api/v1/device-types", { query: { limit: 500 } }) });
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: () => api.get<PageType<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }) });
  const entityTypes = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<PageType<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const [typeId, setTypeId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [entityTypeId, setEntityTypeId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [result, setResult] = useState<BulkCreateResult | null>(null);
  const create = useMutationToast({
    mutationFn: () => api.post<BulkCreateResult>("/api/v1/attention/identities/bulk-create-devices", { body: { identity_ids: identities.map((i) => i.id), device_type_id: typeId, project_id: projectId || null, entity_type_id: entityTypeId || null, group_id: entityTypeId && groupId ? groupId : null } }),
    invalidate: [queryKeys.unknownIdentities, queryKeys.attentionSummary, queryKeys.devices({})],
    success: t("Devices created; the retained events are processed in the background"),
    onSuccess: (data: BulkCreateResult) => { setResult(data); onDone(); if (data.skipped.length === 0) onClose(); },
  });
  const names = identities.map(platformName);
  const open = identities.length > 0;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t("Create {{count}} devices", { count: identities.length })}</DialogTitle></DialogHeader>
        {result ? (
          <div className="space-y-2 text-sm">
            <Callout kind="info">{t("{{created}} devices and {{entities}} entities created, {{queued}} retained events handed to the decoder; they are processed in the background.", { created: result.created, entities: result.entities, queued: result.queued })}</Callout>
            {result.skipped.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs">{result.skipped.map((s) => <li key={s.identity_id}><span className="font-mono">{s.external_id ?? s.identity_id}</span>: {s.reason}</li>)}</ul>}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{t("Names come from the platform where it sends one, else the external id:")} <span className="font-mono">{names.slice(0, 5).join(", ")}{names.length > 5 ? ` … (+${names.length - 5})` : ""}</span></p>
            <Field label={t("Device type")} htmlFor="bulk-device-type">
              <Select value={typeId} onValueChange={setTypeId}><SelectTrigger id="bulk-device-type"><SelectValue placeholder={t("Choose")} /></SelectTrigger><SelectContent>{types.data?.items.map((dt) => <SelectItem key={dt.id} value={dt.id}>{dt.label} ({dt.driver_key})</SelectItem>)}</SelectContent></Select>
            </Field>
            <Field label={t("Assign to project")} htmlFor="bulk-device-project" hint={t("From the first time each identity was seen")}>
              <Select value={projectId || "none"} onValueChange={(v) => { setProjectId(v === "none" ? "" : v); setGroupId(""); if (v === "none") setEntityTypeId(""); }}><SelectTrigger id="bulk-device-project"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{t("No project yet")}</SelectItem>{projects.data?.items.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
            </Field>
            <Field label={t("Also create an entity per device")} htmlFor="bulk-entity-type" hint={projectId ? t("Each device gets an entity of this type with the same name, assigned from the same time, so it shows on the map at once") : t("Needs a project")}>
              <Select value={entityTypeId || "none"} onValueChange={(v) => setEntityTypeId(v === "none" ? "" : v)} disabled={!projectId}><SelectTrigger id="bulk-entity-type"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{t("No entity")}</SelectItem>{entityTypes.data?.items.map((et) => <SelectItem key={et.id} value={et.id}>{et.label}</SelectItem>)}</SelectContent></Select>
            </Field>
            {projectId && entityTypeId && (
              <Field label={t("Put the entities in a group")} htmlFor="bulk-group">
                <GroupSelect id="bulk-group" projectId={projectId} mode="choice" value={groupId} onChange={setGroupId} />
              </Field>
            )}
          </div>
        )}
        <DialogFooter>
          {result ? <Button onClick={onClose}>{t("Close")}</Button> : <><Button variant="outline" onClick={onClose}>{t("Cancel")}</Button><Button disabled={!typeId || create.isPending} onClick={() => create.mutate()}>{t("Create and reprocess")}</Button></>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** A metric that registered itself: label, unit and category in one row (decision D102). */
function NewMetricRow({ metric, categories, onDefined }: { metric: NewMetric; categories: string[]; onDefined: () => void }) {
  const { t } = useTranslation();
  const [label, setLabel] = useState(metric.label);
  const [unit, setUnit] = useState(metric.unit ?? "");
  const [category, setCategory] = useState(categories[0] ?? "");
  const define = useMutationToast({
    mutationFn: () => api.patch(`/api/v1/metrics/${metric.key}`, { body: { label, unit: unit || null, category } }),
    invalidate: [queryKeys.newMetrics, queryKeys.attentionSummary],
    success: t("Metric defined"),
    onSuccess: onDefined,
  });
  return (
    <div className="grid items-center gap-2 border-b px-3 py-2 text-sm md:grid-cols-[1fr_1.2fr_6rem_10rem_auto]">
      <div><span className="font-mono text-xs">{metric.key}</span><div className="text-xs text-muted-foreground">{t("{{count}} devices, last {{when}}", { count: metric.devices, when: formatAgo(metric.last_time) })}{metric.sample != null ? `, ${String(metric.sample)}` : ""}</div></div>
      <Input value={label} onChange={(e) => setLabel(e.target.value)} aria-label={t("Label")} />
      <Input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder={t("unit")} aria-label={t("Unit")} />
      <Select value={category} onValueChange={setCategory}><SelectTrigger aria-label={t("Category")}><SelectValue placeholder={t("Category")} /></SelectTrigger><SelectContent>{categories.map((c) => <SelectItem key={c} value={c}>{c.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select>
      <Button size="sm" disabled={!label || !category || define.isPending} onClick={() => define.mutate()}>{t("Define")}</Button>
    </div>
  );
}

export function AttentionPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const summary = useQuery({ queryKey: queryKeys.attentionSummary, queryFn: () => api.get<AttentionSummary>("/api/v1/attention/summary"), refetchInterval: (query) => (query.state.data?.queued_source_events ? 3_000 : 30_000) });
  const clocks = useQuery({ queryKey: ["attention", "clock-ahead"], queryFn: () => api.get<ClockAheadDevice[]>("/api/v1/attention/clock-ahead"), refetchInterval: 60_000 });
  const clockColumns: ColumnDef<ClockAheadDevice, unknown>[] = [
    { header: t("Device"), accessorKey: "name", cell: ({ row }) => <Link className="underline" to={`/admin/devices/${row.original.device_id}`}>{row.original.name}</Link> },
    { header: t("Positions"), accessorKey: "positions" },
    { header: t("Measurements"), accessorKey: "measurements" },
    { header: t("Device time up to"), accessorKey: "until", cell: ({ getValue }) => formatTime(getValue<string>()) },
  ];
  const identities = useQuery({ queryKey: queryKeys.unknownIdentities, queryFn: () => api.get<PageType<UnknownIdentity>>("/api/v1/attention/identities", { query: { limit: 200 } }) });
  const failed = useQuery({ queryKey: queryKeys.failedSourceEvents("failed"), queryFn: () => api.get<SourceEventSummary[]>("/api/v1/attention/source-events", { query: { status: "failed", limit: 200 } }) });
  const newMetrics = useQuery({ queryKey: queryKeys.newMetrics, queryFn: () => api.get<NewMetricsResponse>("/api/v1/attention/metrics") });
  const [topic, setTopic] = useState(DEAD_TOPICS[0]);
  const dead = useQuery({ queryKey: queryKeys.deadLetters(topic), queryFn: () => api.get<DeadLetter[]>("/api/v1/attention/dead-letters", { query: { topic, limit: 200 } }) });
  const [creating, setCreating] = useState<UnknownIdentity | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [bulk, setBulk] = useState<UnknownIdentity[]>([]);
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(null);
  const [trace, setTrace] = useState<string | null>(null);
  const invalidateAll = [queryKeys.unknownIdentities, queryKeys.attentionSummary, queryKeys.failedSourceEvents("failed"), queryKeys.deadLetters(topic)];
  const ignore = useMutationToast({ mutationFn: (id: string) => api.post(`/api/v1/attention/identities/${id}/ignore`), invalidate: invalidateAll, success: t("Identity ignored") });
  const ignoreMany = useMutationToast({ mutationFn: (ids: string[]) => api.post<BulkIgnoreResult>("/api/v1/attention/identities/bulk-ignore", { body: { identity_ids: ids } }), invalidate: invalidateAll, success: t("Identities ignored"), onSuccess: () => setSelected(new Set()) });
  const selectedIdentities = (identities.data?.items ?? []).filter((i) => selected.has(i.id));
  const reprocess = useMutationToast({ mutationFn: (e: SourceEventSummary) => api.post(`/api/v1/attention/source-events/${e.id}/reprocess`, { query: { ingested_at: e.ingested_at } }), invalidate: invalidateAll, success: t("Source event put back on the bus") });
  const retry = useMutationToast({ mutationFn: (d: DeadLetter) => api.post(`/api/v1/attention/dead-letters/${d.topic}/${d.id}/retry`), invalidate: invalidateAll, success: t("Message republished") });
  const resolve = useMutationToast({ mutationFn: (d: DeadLetter) => api.post(`/api/v1/attention/dead-letters/${d.topic}/${d.id}/resolve`), invalidate: invalidateAll, success: t("Dead letter resolved") });

  const identityColumns: ColumnDef<UnknownIdentity, unknown>[] = [
    { header: t("External id"), accessorKey: "external_id", meta: { filter: "text" }, cell: ({ getValue }) => <span className="font-mono">{getValue<string>()}</span> },
    { header: t("Name"), id: "name", accessorFn: (row) => (typeof row.attributes?.name === "string" ? row.attributes.name : ""), meta: { filter: "text" }, cell: ({ getValue }) => getValue<string>() || <span className="text-muted-foreground">{t("none")}</span> },
    { header: t("Data source"), accessorKey: "data_source_name" },
    { header: t("Type"), accessorKey: "identity_type" },
    { header: t("First seen"), accessorKey: "first_seen_at", meta: { filter: false }, cell: ({ getValue }) => formatTime(getValue<string | null>()) },
    { header: t("Last seen"), accessorKey: "last_seen_at", meta: { filter: false }, cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
    { header: t("Events"), accessorKey: "event_count", meta: { filter: false } },
    { id: "actions", header: "", cell: ({ row }) => <div className="flex gap-1"><Button size="sm" onClick={() => setCreating(row.original)}>{t("Create device")}</Button><Button size="sm" variant="ghost" onClick={() => ignore.mutate(row.original.id)}>{t("Ignore")}</Button></div> },
  ];
  const failedColumns: ColumnDef<SourceEventSummary, unknown>[] = [
    { header: t("Ingested"), accessorKey: "ingested_at", meta: { filter: false }, cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("External id"), accessorKey: "external_id", meta: { filter: "text" }, cell: ({ getValue }) => <span className="font-mono">{getValue<string | null>()}</span> },
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
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label={t("Unknown identities")} value={s?.unknown_identities ?? "…"} tone={s?.unknown_identities ? "warn" : undefined} />
          <Stat label={t("Unassigned source events")} value={s?.unassigned_source_events ?? "…"} tone={s?.unassigned_source_events ? "warn" : undefined} />
          <Stat label={t("Failed source events")} value={s?.failed_source_events ?? "…"} tone={s?.failed_source_events ? "bad" : undefined} />
          <Stat label={t("Dead letters")} value={s ? Object.values(s.dead_letters).reduce((a, b) => a + b, 0) : "…"} tone={s && Object.keys(s.dead_letters).length ? "bad" : undefined} />
          <Stat label={t("New metrics")} value={s?.uncategorized_metrics ?? "…"} tone={s?.uncategorized_metrics ? "warn" : undefined} />
          <Stat label={t("Clocks ahead")} value={s?.clock_ahead_devices ?? "…"} tone={s?.clock_ahead_devices ? "warn" : undefined} />
        </div>
        <QueueProgress queued={s?.queued_source_events ?? 0} onDrained={() => { for (const key of invalidateAll) void queryClient.invalidateQueries({ queryKey: key }); void queryClient.invalidateQueries({ queryKey: queryKeys.devices({}) }); }} />
        <Tabs defaultValue="identities">
          <TabsList><TabsTrigger value="identities">{t("Unknown identities")}</TabsTrigger><TabsTrigger value="metrics">{t("New metrics")}</TabsTrigger><TabsTrigger value="clocks">{t("Clocks ahead")}</TabsTrigger><TabsTrigger value="failed">{t("Failed source events")}</TabsTrigger><TabsTrigger value="dead">{t("Dead letters")}</TabsTrigger></TabsList>
          <TabsContent value="metrics">
            <div className="rounded-md border">
              <p className="border-b px-3 py-2 text-xs text-muted-foreground">{t("Metrics a device sent that nobody defined yet. They are stored and charted already; give each a label, a unit and a category.")}</p>
              {(newMetrics.data?.items ?? []).map((m) => <NewMetricRow key={m.key} metric={m} categories={newMetrics.data?.categories ?? []} onDefined={() => undefined} />)}
              {newMetrics.data && newMetrics.data.items.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted-foreground">{t("Every metric is defined.")}</p>}
            </div>
          </TabsContent>
          <TabsContent value="clocks">
            <div className="rounded-md border">
              <p className="border-b px-3 py-2 text-xs text-muted-foreground">{t("Devices whose records carry a device time ahead of the clock. The records are kept but invalid, so they stay off the map and out of the analysis, and the device's last seen does not move. Fix: on the device's project, Analyze, Curation, a bulk job with a time offset and the reason Device clock error.")}</p>
              <DataTable columns={clockColumns} data={clocks.data} isLoading={clocks.isPending} emptyMessage={t("Every device clock is within an hour of the delivery.")} />
            </div>
          </TabsContent>
          <TabsContent value="identities" className="space-y-2">
            {selected.size > 0 && (
              <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                <span>{t("{{count}} selected", { count: selected.size })}</span>
                <Button size="sm" onClick={() => setBulk(selectedIdentities)}>{t("Create devices")}</Button>
                <Button size="sm" variant="outline" disabled={ignoreMany.isPending} onClick={() => ignoreMany.mutate([...selected])}>{t("Ignore")}</Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>{t("Clear selection")}</Button>
              </div>
            )}
            <DataTable columns={identityColumns} data={identities.data?.items} searchable columnFilters isLoading={identities.isPending} emptyMessage={t("Every identity is linked to a device.")} selection={{ selected, onChange: setSelected, rowId: (row) => row.id }} />
          </TabsContent>
          <TabsContent value="failed"><DataTable columns={failedColumns} data={failed.data} searchable columnFilters isLoading={failed.isPending} emptyMessage={t("No failed source events.")} /></TabsContent>
          <TabsContent value="dead" className="space-y-3">
            <Select value={topic} onValueChange={setTopic}><SelectTrigger className="w-72"><SelectValue /></SelectTrigger><SelectContent>{DEAD_TOPICS.map((t) => <SelectItem key={t} value={t}>{t} {s?.dead_letters[t] ? `(${s.dead_letters[t]})` : ""}</SelectItem>)}</SelectContent></Select>
            <DataTable columns={deadColumns} data={dead.data} searchable isLoading={dead.isPending} emptyMessage={t("No dead letters on this topic.")} />
          </TabsContent>
        </Tabs>
      </Page>
      <CreateDeviceDialog identity={creating} onClose={() => setCreating(null)} />
      <BulkCreateDialog identities={bulk} onClose={() => setBulk([])} onDone={() => setSelected(new Set())} />
      <SourceEventDialog id={event?.id ?? null} ingestedAt={event?.ingestedAt ?? null} onClose={() => setEvent(null)} />
      <TraceDialog traceId={trace} onClose={() => setTrace(null)} />
    </>
  );
}
