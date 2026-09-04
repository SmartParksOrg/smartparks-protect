import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { History, Plus, RotateCcw, Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useParams, useSearchParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Entity, Integration, IntegrationDelivery, IntegrationDeliveryDetail, IntegrationDetail, IntegrationTestResult, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";
import { SEVERITIES } from "@/lib/rules";

interface ConnectorInfo {
  key: string;
  label: string;
  description: string;
  supports: string[];
  config_schema: Record<string, unknown>;
  config_example: Record<string, unknown>;
  credentials_schema: Record<string, string>;
  setup_hint: string;
}

const OBJECT_TYPES = ["position", "event", "measurement"] as const;
const DELIVERY_STATUSES = ["queued", "sent", "failed", "skipped"] as const;

const jsonObject = (allowEmpty: boolean) => (v: string) => { if (allowEmpty && !v.trim()) return true; try { return typeof JSON.parse(v) === "object"; } catch { return false; } };
const schema = z.object({
  name: z.string().min(1).max(200),
  description: z.string(),
  connector_key: z.string().min(1),
  enabled: z.boolean(),
  config: z.string().refine(jsonObject(false), "Must be a JSON object"),
  credentials: z.string().refine(jsonObject(true), "Must be a JSON object or empty"),
  object_types: z.array(z.enum(OBJECT_TYPES)).min(1, "Forward at least one kind of object"),
  entity_ids: z.array(z.string()),
  event_types: z.string(),
  metric_keys: z.string(),
  min_severity: z.enum(["info", "warning", "critical"]),
  max_object_age_hours: z.number().min(0.02).max(24 * 365),
});
type Values = z.infer<typeof schema>;

const credentialsTemplate = (c: ConnectorInfo | undefined) => Object.fromEntries(Object.keys(c?.credentials_schema ?? {}).map((k) => [k, ""]));

function toValues(i: Integration | null, connector: ConnectorInfo | undefined): Values {
  return i
    ? { name: i.name, description: i.description ?? "", connector_key: i.connector_key, enabled: i.enabled, config: JSON.stringify(i.config, null, 2), credentials: "", object_types: i.object_types as Values["object_types"], entity_ids: i.entity_ids, event_types: i.event_types.join(", "), metric_keys: i.metric_keys.join(", "), min_severity: i.min_severity as Values["min_severity"], max_object_age_hours: i.max_object_age_seconds / 3600 }
    : { name: "", description: "", connector_key: connector?.key ?? "", enabled: true, config: JSON.stringify(connector?.config_example ?? {}, null, 2), credentials: JSON.stringify(credentialsTemplate(connector), null, 2), object_types: (connector?.supports.filter((s) => s !== "measurement") as Values["object_types"]) ?? ["position", "event"], entity_ids: [], event_types: "", metric_keys: "", min_severity: "info", max_object_age_hours: 24 };
}

function toBody(v: Values, editing: boolean) {
  const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
  const body: Record<string, unknown> = {
    name: v.name,
    description: v.description || null,
    enabled: v.enabled,
    config: JSON.parse(v.config) as Record<string, unknown>,
    object_types: v.object_types,
    entity_ids: v.entity_ids,
    event_types: list(v.event_types),
    metric_keys: list(v.metric_keys),
    min_severity: v.min_severity,
    max_object_age_seconds: Math.round(v.max_object_age_hours * 3600),
  };
  if (v.credentials.trim()) body.credentials = JSON.parse(v.credentials);
  if (!editing) body.connector_key = v.connector_key;
  return body;
}

const dateLocal = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);

/** Outbound integrations (architecture 18): what leaves the platform, to where, and what happened to every object. */
export function IntegrationsPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "deliveries" ? "deliveries" : "integrations";
  const base = `/api/v1/projects/${projectId}/integrations`;
  const connectors = useQuery({ queryKey: queryKeys.integrationConnectors(projectId), queryFn: () => api.get<ConnectorInfo[]>(`${base}/connectors`) });
  const CONNECTORS = connectors.data ?? [];
  const integrations = useQuery({ queryKey: queryKeys.integrations(projectId), queryFn: () => api.get<PageType<Integration>>(base, { query: { limit: 500 } }), refetchInterval: 15_000 });
  const entities = useQuery({ queryKey: queryKeys.entities(projectId), queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }) });
  const deliveryStatus = params.get("status") ?? "";
  const deliveryIntegration = params.get("integration") ?? "";
  const deliveries = useQuery({ queryKey: queryKeys.integrationDeliveries(projectId, { status: deliveryStatus, integration: deliveryIntegration }), queryFn: () => api.get<PageType<IntegrationDelivery>>(`${base}/deliveries`, { query: { limit: 200, status: deliveryStatus || undefined, integration_id: deliveryIntegration || undefined } }), enabled: tab === "deliveries", refetchInterval: tab === "deliveries" ? 10_000 : false });
  const [editing, setEditing] = useState<Integration | null>(null);
  const [open, setOpen] = useState(false);
  const [removing, setRemoving] = useState<Integration | null>(null);
  const [inspecting, setInspecting] = useState<Integration | null>(null);
  const [backfilling, setBackfilling] = useState<Integration | null>(null);
  const [backfillRange, setBackfillRange] = useState({ from: dateLocal(new Date(Date.now() - 7 * 86_400_000)), to: dateLocal(new Date()) });
  const [testing, setTesting] = useState<Integration | null>(null);
  const [testLocation, setTestLocation] = useState({ latitude: "", longitude: "" });
  const [testResult, setTestResult] = useState<IntegrationTestResult | null>(null);
  const [deliveryDetail, setDeliveryDetail] = useState<IntegrationDelivery | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(null, undefined) });
  const connectorKey = form.watch("connector_key");
  const connector = CONNECTORS.find((c) => c.key === connectorKey);
  useEffect(() => { if (open) form.reset(toValues(editing, editing ? CONNECTORS.find((c) => c.key === editing.connector_key) : CONNECTORS[0])); }, [open, editing, form, CONNECTORS]);
  const detail = useQuery({ queryKey: queryKeys.integration(projectId, inspecting?.id ?? ""), queryFn: () => api.get<IntegrationDetail>(`${base}/${inspecting?.id}`), enabled: inspecting !== null, refetchInterval: inspecting ? 5_000 : false });
  const delivery = useQuery({ queryKey: queryKeys.integrationDelivery(projectId, deliveryDetail?.id ?? ""), queryFn: () => api.get<IntegrationDeliveryDetail>(`${base}/deliveries/${deliveryDetail?.id}`), enabled: deliveryDetail !== null });
  const invalidate = [queryKeys.integrations(projectId)];
  const save = useMutationToast({
    mutationFn: (v: Values) => (editing ? api.patch<Integration>(`${base}/${editing.id}`, { body: toBody(v, true) }) : api.post<Integration>(base, { body: toBody(v, false) })),
    invalidate,
    success: editing ? "Integration saved" : "Integration created",
    onSuccess: () => setOpen(false),
    onError: (e) => form.setError("root", { message: e.message }),
  });
  const toggle = useMutationToast({ mutationFn: ({ i, enabled }: { i: Integration; enabled: boolean }) => api.patch<Integration>(`${base}/${i.id}`, { body: { enabled } }), invalidate, success: (i) => (i.enabled ? "Integration enabled" : "Integration disabled") });
  const remove = useMutationToast({ mutationFn: (i: Integration) => api.delete<void>(`${base}/${i.id}`), invalidate, success: "Integration deleted", onSuccess: () => setRemoving(null) });
  const test = useMutationToast({
    mutationFn: (i: Integration) => api.post<IntegrationTestResult>(`${base}/${i.id}/test`, { body: { latitude: testLocation.latitude ? Number(testLocation.latitude) : null, longitude: testLocation.longitude ? Number(testLocation.longitude) : null } }),
    invalidate,
    onSuccess: (r) => setTestResult(r),
  });
  const backfill = useMutationToast({
    mutationFn: (i: Integration) => api.post<Integration>(`${base}/${i.id}/backfill`, { body: { time_from: new Date(backfillRange.from).toISOString(), time_to: new Date(backfillRange.to).toISOString() } }),
    invalidate,
    success: "Backfill queued; the integration service works through the range in batches",
    onSuccess: () => setBackfilling(null),
  });
  const retry = useMutationToast({ mutationFn: (d: IntegrationDelivery) => api.post<IntegrationDelivery>(`${base}/deliveries/${d.id}/retry`), invalidate: [queryKeys.integrationDeliveries(projectId, { status: deliveryStatus, integration: deliveryIntegration })], success: "Queued again", onSuccess: () => setDeliveryDetail(null) });
  const connectorLabel = (key: string) => CONNECTORS.find((c) => c.key === key)?.label ?? key;
  const integrationName = (id: string) => integrations.data?.items.find((i) => i.id === id)?.name ?? "";
  const entityName = (id: string | null | undefined) => entities.data?.items.find((e) => e.id === id)?.name ?? "";

  const columns: ColumnDef<Integration, unknown>[] = [
    { header: "Enabled", accessorKey: "enabled", cell: ({ row }) => <span onClick={(e) => e.stopPropagation()}><Switch checked={row.original.enabled} aria-label={`Enable ${row.original.name}`} onCheckedChange={(v) => toggle.mutate({ i: row.original, enabled: v })} /></span> },
    { header: "Name", accessorKey: "name" },
    { header: "Target", accessorKey: "connector_key", cell: ({ getValue }) => connectorLabel(getValue<string>()) },
    { header: "Forwards", id: "forwards", cell: ({ row }) => <span className="text-xs">{row.original.object_types.join(", ")}{row.original.event_types.length ? `; ${row.original.event_types.join(", ")}` : ""}{row.original.entity_ids.length ? `; ${row.original.entity_ids.length} entities` : ""}</span> },
    { header: "Last delivery", accessorKey: "last_delivery_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) },
    { header: "Status", id: "status", cell: ({ row }) => row.original.last_error ? <span className="text-xs text-destructive" title={row.original.last_error}>{row.original.last_error.slice(0, 60)}</span> : row.original.backfill?.status ? <StatusBadge value={String(row.original.backfill.status)} /> : <StatusBadge value="ok" /> },
    { id: "actions", header: "", cell: ({ row }) => <span className="flex gap-1" onClick={(e) => e.stopPropagation()}>
      <Button variant="ghost" size="sm" aria-label="Test" onClick={() => { setTestResult(null); setTesting(row.original); }}><Send className="size-4" /></Button>
      <Button variant="ghost" size="sm" aria-label="Backfill" onClick={() => setBackfilling(row.original)}><History className="size-4" /></Button>
      <Button variant="ghost" size="icon" aria-label="Delete integration" onClick={() => setRemoving(row.original)}><Trash2 className="size-4" /></Button>
    </span> },
  ];
  const deliveryColumns: ColumnDef<IntegrationDelivery, unknown>[] = [
    { header: "Created", accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: "Integration", accessorKey: "integration_id", cell: ({ getValue }) => integrationName(getValue<string>()) },
    { header: "Object", id: "object", cell: ({ row }) => <span className="text-xs">{row.original.object_type} {row.original.object_type === "event" ? row.original.object_id.slice(0, 8) : row.original.object_id}<span className="text-muted-foreground"> at {formatTime(row.original.object_time)}</span></span> },
    { header: "Entity", accessorKey: "entity_id", cell: ({ getValue }) => entityName(getValue<string | null>()) },
    { header: "Origin", accessorKey: "origin" },
    { header: "Status", accessorKey: "status", cell: ({ row }) => <span className="inline-flex items-center gap-2"><StatusBadge value={row.original.status} /><span className="text-xs text-muted-foreground">{row.original.attempts} attempt{row.original.attempts === 1 ? "" : "s"}</span></span> },
    { header: "Detail", id: "detail", cell: ({ row }) => <span className="text-xs">{row.original.external_id ? `ref ${row.original.external_id}` : row.original.error_message ?? (row.original.next_attempt_at ? `next ${formatTime(row.original.next_attempt_at)}` : "")}</span> },
  ];

  return (
    <>
      <PageHeader title="Integrations" description="Durable outbound delivery of positions, events and measurements to external platforms, webhooks and MQTT brokers, with retries, a delivery log and backfill" actions={<Button onClick={() => { setEditing(null); setOpen(true); }} disabled={CONNECTORS.length === 0}><Plus className="size-4" /> New integration</Button>} />
      <Page>
        <div className="flex flex-wrap items-center gap-3">
          <Tabs value={tab} onValueChange={(v) => setParams((p) => { p.set("tab", v); return p; }, { replace: true })}><TabsList><TabsTrigger value="integrations">Integrations</TabsTrigger><TabsTrigger value="deliveries">Deliveries</TabsTrigger></TabsList></Tabs>
          {tab === "deliveries" && (
            <>
              <Select value={deliveryStatus || "all"} onValueChange={(v) => setParams((p) => { if (v === "all") p.delete("status"); else p.set("status", v); return p; }, { replace: true })}>
                <SelectTrigger className="w-36" aria-label="Delivery status"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">Any status</SelectItem>{DELIVERY_STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
              <Select value={deliveryIntegration || "all"} onValueChange={(v) => setParams((p) => { if (v === "all") p.delete("integration"); else p.set("integration", v); return p; }, { replace: true })}>
                <SelectTrigger className="w-48" aria-label="Integration filter"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">Any integration</SelectItem>{integrations.data?.items.map((i) => <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>)}</SelectContent>
              </Select>
            </>
          )}
        </div>
        {(integrations.error ?? deliveries.error ?? connectors.error) && <Callout kind="error">{(integrations.error ?? deliveries.error ?? connectors.error)?.message}</Callout>}
        {tab === "integrations" ? (
          <DataTable columns={columns} data={integrations.data?.items} isLoading={integrations.isPending} emptyMessage="No integrations yet. Create one to forward this project's positions and events to an external system." onRowClick={(i) => setInspecting(i)} />
        ) : (
          <DataTable columns={deliveryColumns} data={deliveries.data?.items} isLoading={deliveries.isPending} emptyMessage="No deliveries yet." onRowClick={(d) => setDeliveryDetail(d)} footer={deliveries.data && `${deliveries.data.items.length} deliveries, newest first`} />
        )}
      </Page>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>{editing ? "Edit integration" : "New integration"}</DialogTitle><DialogDescription>Every matching object becomes one delivery, sent once and retried on failure. Credentials are encrypted and never shown again.</DialogDescription></DialogHeader>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" htmlFor="in-name" error={form.formState.errors.name?.message}><Input id="in-name" {...form.register("name")} /></Field>
              <Field label="Target" htmlFor="in-connector">
                <Select value={connectorKey} disabled={Boolean(editing)} onValueChange={(v) => { form.setValue("connector_key", v); const c = CONNECTORS.find((x) => x.key === v); if (c && !editing) { form.setValue("config", JSON.stringify(c.config_example, null, 2)); form.setValue("credentials", JSON.stringify(credentialsTemplate(c), null, 2)); form.setValue("object_types", c.supports.filter((s) => s !== "measurement") as Values["object_types"]); } }}>
                  <SelectTrigger id="in-connector"><SelectValue /></SelectTrigger>
                  <SelectContent>{CONNECTORS.map((c) => <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
            </div>
            {connector && <Callout kind="info"><div>{connector.description}.</div>{connector.setup_hint && <div className="mt-1 text-xs">{connector.setup_hint}</div>}</Callout>}
            <Field label="Description" htmlFor="in-description"><Input id="in-description" {...form.register("description")} /></Field>
            <Field label="Forward" htmlFor="in-types" error={form.formState.errors.object_types?.message}>
              <div className="flex flex-wrap gap-2" id="in-types">
                {OBJECT_TYPES.map((t) => { const supported = connector?.supports.includes(t) ?? true; const on = form.watch("object_types").includes(t); return <Button key={t} type="button" size="sm" variant={on ? "default" : "outline"} disabled={!supported} title={supported ? undefined : `${connector?.label} cannot receive ${t}s`} onClick={() => form.setValue("object_types", on ? form.getValues("object_types").filter((x) => x !== t) : [...form.getValues("object_types"), t])}>{t}s</Button>; })}
              </div>
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Event types" htmlFor="in-events" hint="Comma separated; empty means every type"><Input id="in-events" placeholder="GEOFENCE_EXIT, SPECIES_DETECTION" {...form.register("event_types")} /></Field>
              <Field label="Minimum event severity" htmlFor="in-severity">
                <Select value={form.watch("min_severity")} onValueChange={(v) => form.setValue("min_severity", v as Values["min_severity"])}>
                  <SelectTrigger id="in-severity"><SelectValue /></SelectTrigger>
                  <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Metric keys" htmlFor="in-metrics" hint="For measurements; empty means every metric"><Input id="in-metrics" placeholder="battery_voltage, temperature" {...form.register("metric_keys")} /></Field>
              <Field label="Skip live objects older than (hours)" htmlFor="in-age" hint="Backfill ignores this bound" error={form.formState.errors.max_object_age_hours?.message}><Input id="in-age" type="number" step="any" {...form.register("max_object_age_hours", { valueAsNumber: true })} /></Field>
            </div>
            <Field label="Entities" htmlFor="in-entities" hint="Optional. Leave empty for every entity of the project.">
              <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto" id="in-entities">
                {entities.data?.items.map((e) => { const on = form.watch("entity_ids").includes(e.id); return <Button key={e.id} type="button" size="sm" variant={on ? "default" : "outline"} onClick={() => form.setValue("entity_ids", on ? form.getValues("entity_ids").filter((x) => x !== e.id) : [...form.getValues("entity_ids"), e.id])}>{e.name}</Button>; })}
              </div>
            </Field>
            <Field label="Configuration (JSON)" htmlFor="in-config" error={form.formState.errors.config?.message}><Textarea id="in-config" rows={6} className="font-mono text-xs" {...form.register("config")} /></Field>
            <Field label="Credentials (JSON)" htmlFor="in-credentials" hint={editing ? "Leave empty to keep the stored credentials" : Object.entries(connector?.credentials_schema ?? {}).map(([k, v]) => `${k}: ${v}`).join("; ")} error={form.formState.errors.credentials?.message}><Textarea id="in-credentials" rows={3} className="font-mono text-xs" {...form.register("credentials")} /></Field>
            <div className="flex items-center gap-2"><Switch id="in-enabled" checked={form.watch("enabled")} onCheckedChange={(v) => form.setValue("enabled", v)} /><label htmlFor="in-enabled" className="text-sm">Enabled</label></div>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" disabled={save.isPending}>Save</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={inspecting !== null} onOpenChange={(o) => !o && setInspecting(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader><DialogTitle>{inspecting?.name}</DialogTitle><DialogDescription>{inspecting && connectorLabel(inspecting.connector_key)}{inspecting?.description ? `. ${inspecting.description}` : ""}</DialogDescription></DialogHeader>
          {detail.data && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {DELIVERY_STATUSES.map((s) => <div key={s} className="rounded-md border p-2"><div className="text-xs text-muted-foreground">{s}</div><div className="text-lg font-semibold">{(detail.data.counts ?? {})[s] ?? 0}</div><div className="text-xs text-muted-foreground">{(detail.data.counts_24h ?? {})[s] ?? 0} in 24 h</div></div>)}
              </div>
              {detail.data.last_error && <Callout kind="warning">Last error {formatTime(detail.data.last_error_at)}: {detail.data.last_error}</Callout>}
              {Boolean(detail.data.backfill?.status) && <Callout kind="info">Backfill {String(detail.data.backfill.status)}: {String(detail.data.backfill.queued ?? 0)} queued of {String(detail.data.backfill.scanned ?? 0)} scanned, {String(detail.data.backfill.from ?? "")} to {String(detail.data.backfill.to ?? "")}{detail.data.backfill.error ? `; ${String(detail.data.backfill.error)}` : ""}</Callout>}
              <JsonView value={detail.data.config} />
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setInspecting(null); setParams((p) => { p.set("tab", "deliveries"); if (inspecting) p.set("integration", inspecting.id); return p; }); }}>Show deliveries</Button>
            <Button onClick={() => { setEditing(inspecting); setInspecting(null); setOpen(true); }}>Edit</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={testing !== null} onOpenChange={(o) => !o && setTesting(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Test {testing?.name}</DialogTitle><DialogDescription>Sends a test object to the target. Without coordinates the latest entity position of the project is used.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Latitude" htmlFor="test-lat"><Input id="test-lat" type="number" step="any" value={testLocation.latitude} onChange={(e) => setTestLocation((t) => ({ ...t, latitude: e.target.value }))} /></Field>
            <Field label="Longitude" htmlFor="test-lon"><Input id="test-lon" type="number" step="any" value={testLocation.longitude} onChange={(e) => setTestLocation((t) => ({ ...t, longitude: e.target.value }))} /></Field>
          </div>
          {testResult && <Callout kind={testResult.ok ? "success" : "error"}>{testResult.detail}{testResult.ok && Object.keys(testResult.response ?? {}).length > 0 && <JsonView value={testResult.response} className="mt-2" />}</Callout>}
          <DialogFooter><Button variant="outline" onClick={() => setTesting(null)}>Close</Button><Button disabled={test.isPending} onClick={() => testing && test.mutate(testing)}>Send test</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={backfilling !== null} onOpenChange={(o) => !o && setBackfilling(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Backfill {backfilling?.name}</DialogTitle><DialogDescription>Queues every matching object in the range that was not sent before. Objects already delivered are skipped, so a repeated backfill is harmless.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="From" htmlFor="bf-from"><Input id="bf-from" type="datetime-local" value={backfillRange.from} onChange={(e) => setBackfillRange((r) => ({ ...r, from: e.target.value }))} /></Field>
            <Field label="To" htmlFor="bf-to"><Input id="bf-to" type="datetime-local" value={backfillRange.to} onChange={(e) => setBackfillRange((r) => ({ ...r, to: e.target.value }))} /></Field>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setBackfilling(null)}>Cancel</Button><Button disabled={backfill.isPending} onClick={() => backfilling && backfill.mutate(backfilling)}>Queue backfill</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deliveryDetail !== null} onOpenChange={(o) => !o && setDeliveryDetail(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>Delivery of {deliveryDetail?.object_type} {deliveryDetail?.object_type === "event" ? deliveryDetail.object_id.slice(0, 8) : deliveryDetail?.object_id}</DialogTitle><DialogDescription>{deliveryDetail && `${integrationName(deliveryDetail.integration_id)}, ${deliveryDetail.origin}, ${deliveryDetail.attempts} attempt${deliveryDetail.attempts === 1 ? "" : "s"}`}</DialogDescription></DialogHeader>
          {deliveryDetail && (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge value={deliveryDetail.status} />{deliveryDetail.delivered_at && <span className="text-xs text-muted-foreground">delivered {formatTime(deliveryDetail.delivered_at)}</span>}{deliveryDetail.external_id && <span className="text-xs">target ref {deliveryDetail.external_id}</span>}{deliveryDetail.trace_id && <a className="text-xs underline" href={`/projects/${projectId}/network/traces?trace=${deliveryDetail.trace_id}`}>trace</a>}</div>
              {deliveryDetail.error_message && <Callout kind={deliveryDetail.status === "failed" ? "error" : "warning"}>{deliveryDetail.error_message}</Callout>}
              <div><div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Request</div><JsonView value={delivery.data?.request ?? null} /></div>
              <div><div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Response</div><JsonView value={delivery.data?.response ?? {}} /></div>
            </div>
          )}
          <DialogFooter><Button variant="outline" onClick={() => setDeliveryDetail(null)}>Close</Button>{deliveryDetail && deliveryDetail.status !== "sent" && <Button onClick={() => retry.mutate(deliveryDetail)} disabled={retry.isPending}><RotateCcw className="size-4" /> Retry now</Button>}</DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog open={removing !== null} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete integration ${removing?.name ?? ""}?`} description="Its delivery log is deleted with it." confirmLabel="Delete" pending={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} />
    </>
  );
}
