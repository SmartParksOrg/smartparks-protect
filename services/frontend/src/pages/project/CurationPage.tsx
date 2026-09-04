import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Check, Plus, RotateCcw, Undo2 } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Correction, CurationJob, Device, Entity, IntegrationDelivery, MetricWithData, Page as PageType } from "@/api/types";
import { MultiSelect } from "@/components/analytics/MultiSelect";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { RecordHistoryDialog } from "@/components/curation/CurationDialogs";
import { DataTable } from "@/components/data/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { invalidateRecords, useCurationSummary } from "@/hooks/useCuration";
import { useMutationToast } from "@/hooks/useMutationToast";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { type CurationTarget, FIELD_LABELS, formatValue, REASON_LABELS } from "@/lib/curation";
import { formatAgo, formatTime } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

type Tab = "pending" | "applied" | "jobs" | "reverted" | "impact";
const TABS: Array<[Tab, string]> = [["pending", "Pending"], ["applied", "Applied"], ["jobs", "Bulk jobs"], ["reverted", "Reverted"], ["impact", "Downstream impact"]];
const KINDS: Record<string, string> = { time_offset: "shift time", set_valid: "set validity", value_offset: "add to value", value_scale: "scale value" };

function describeTransformation(t: Record<string, unknown>): string {
  if (t.kind === "time_offset") { const s = Number(t.seconds); return `time ${s >= 0 ? "+" : "-"} ${Math.abs(s)} s (${(Math.abs(s) / 3600).toFixed(2)} h)`; }
  if (t.kind === "set_valid") return t.valid ? "mark valid" : "mark invalid";
  if (t.kind === "value_offset") return `value ${Number(t.delta) >= 0 ? "+" : "-"} ${Math.abs(Number(t.delta))}`;
  return `value x ${t.factor}`;
}

/** Data curation workspace (architecture 28.12): pending changes, applied corrections, bulk
 * jobs, reverted corrections and downstream impact. */
export function CurationPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some(([t]) => t === params.get("tab")) ? params.get("tab") : "pending") as Tab;
  const role = useProjectRole(projectId);
  const user = useAuthStore((s) => s.user);
  const admin = canAdmin(role) || Boolean(user?.is_superuser);
  const client = useQueryClient();
  const summary = useCurationSummary(projectId);
  const base = `/api/v1/projects/${projectId}/curation`;
  const statusFor: Record<Tab, string | undefined> = { pending: "pending", applied: "active", jobs: undefined, reverted: "reverted", impact: undefined };
  const corrections = useQuery({ queryKey: queryKeys.corrections(projectId, { status: statusFor[tab] }), queryFn: () => api.get<PageType<Correction>>(`${base}/corrections`, { query: { status: statusFor[tab], limit: 200 } }), enabled: tab !== "jobs" && tab !== "impact" });
  const superseded = useQuery({ queryKey: queryKeys.corrections(projectId, { status: "superseded" }), queryFn: () => api.get<PageType<Correction>>(`${base}/corrections`, { query: { status: "superseded", limit: 200 } }), enabled: tab === "reverted" });
  const jobs = useQuery({ queryKey: queryKeys.curationJobs(projectId, {}), queryFn: () => api.get<PageType<CurationJob>>(`${base}/jobs`, { query: { limit: 100 } }), refetchInterval: (q) => (q.state.data?.items.some((j) => j.status === "applying" || j.status === "reverting") ? 3_000 : false) });
  const stale = useQuery({ queryKey: queryKeys.integrationDeliveries(projectId, { stale: true }), queryFn: () => api.get<PageType<IntegrationDelivery>>(`/api/v1/projects/${projectId}/integrations/deliveries`, { query: { stale: true, limit: 200 } }), enabled: tab === "impact" });
  const [history, setHistory] = useState<CurationTarget | null>(null);
  const [reverting, setReverting] = useState<{ kind: "correction" | "job"; id: string } | null>(null);
  const [revertComment, setRevertComment] = useState("");
  const [newJob, setNewJob] = useState(false);
  const [job, setJob] = useState<CurationJob | null>(null);
  const invalidateAll = () => { void client.invalidateQueries({ queryKey: ["projects", projectId, "curation"] }); invalidateRecords(client, projectId); };
  const approve = useMutationToast({ mutationFn: (c: Correction) => api.post<Correction>(`${base}/corrections/${c.id}/approve`), success: t("Correction approved and applied"), onSuccess: invalidateAll });
  const revert = useMutationToast({
    mutationFn: (r: { kind: "correction" | "job"; id: string }) => api.post<unknown>(`${base}/${r.kind === "job" ? "jobs" : "corrections"}/${r.id}/revert`, { body: { comment: revertComment || null } }),
    success: t("Reverted"),
    onSuccess: () => { setReverting(null); setRevertComment(""); invalidateAll(); },
  });
  const resend = useMutationToast({ mutationFn: (d: IntegrationDelivery) => api.post<IntegrationDelivery>(`/api/v1/projects/${projectId}/integrations/deliveries/${d.id}/resend`), success: t("Corrected object queued for delivery"), onSuccess: () => { void stale.refetch(); void summary.refetch(); } });

  const correctionColumns: ColumnDef<Correction, unknown>[] = [
    { header: t("When"), accessorKey: "created_at", cell: ({ getValue }) => formatAgo(getValue<string>()) },
    { header: t("Record"), id: "record", cell: ({ row }) => <Button variant="link" size="sm" className="h-auto p-0" onClick={(e) => { e.stopPropagation(); setHistory({ target_type: row.original.target_type as CurationTarget["target_type"], target_id: row.original.target_id, target_time: row.original.target_time }); }}>{row.original.target_type} {row.original.target_id}{row.original.metric_key ? ` (${row.original.metric_key})` : ""}</Button> },
    { header: t("Field"), accessorKey: "field", cell: ({ getValue }) => FIELD_LABELS[getValue<string>()] ?? getValue<string>() },
    { header: t("Change"), id: "change", cell: ({ row }) => <span className="text-xs">{t("{{from}} to {{to}}", { from: formatValue(row.original.field, row.original.original_value), to: formatValue(row.original.field, row.original.corrected_value) })}</span> },
    { header: t("Reason"), accessorKey: "reason_code", cell: ({ row }) => <span className="text-xs">{REASON_LABELS[row.original.reason_code] ?? row.original.reason_code}{row.original.comment ? `: ${row.original.comment}` : ""}</span> },
    { header: t("Status"), accessorKey: "status", cell: ({ row }) => <span className="inline-flex items-center gap-1"><StatusBadge value={row.original.status} />{row.original.curation_job_id && <Badge variant="outline">{t("bulk")}</Badge>}</span> },
    { id: "actions", header: "", cell: ({ row }) => admin ? (
      <span className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
        {row.original.status === "pending" && row.original.created_by_user_id !== user?.id && <Button size="sm" variant="outline" onClick={() => approve.mutate(row.original)}><Check className="size-4" /> {t("Approve")}</Button>}
        {(row.original.status === "pending" || row.original.status === "active") && !row.original.curation_job_id && <Button size="sm" variant="ghost" onClick={() => setReverting({ kind: "correction", id: row.original.id })}><Undo2 className="size-4" /> {t("Revert")}</Button>}
      </span>
    ) : null },
  ];
  const jobColumns: ColumnDef<CurationJob, unknown>[] = [
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatAgo(getValue<string>()) },
    { header: t("Selection"), id: "selection", cell: ({ row }) => <span className="text-xs">{t("{{type}}s, {{devices}} devices, {{from}} to {{to}}", { type: row.original.target_type, devices: row.original.device_ids.length || t("all"), from: formatTime(row.original.time_from), to: formatTime(row.original.time_to) })}</span> },
    { header: t("Transformation"), id: "transformation", cell: ({ row }) => describeTransformation(row.original.transformation as Record<string, unknown>) },
    { header: t("Records"), id: "records", cell: ({ row }) => <span className="text-xs">{row.original.affected_count} {t("affected")}{row.original.applied_count ? `, ${row.original.applied_count} applied` : ""}{row.original.reverted_count ? `, ${row.original.reverted_count} reverted` : ""}</span> },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
  ];
  const staleColumns: ColumnDef<IntegrationDelivery, unknown>[] = [
    { header: t("Object"), id: "object", cell: ({ row }) => <span className="text-xs">{t("{{type}} {{id}} at {{time}}", { type: row.original.object_type, id: row.original.object_id, time: formatTime(row.original.object_time) })}</span> },
    { header: t("Why"), accessorKey: "stale_reason" },
    { header: t("Flagged"), accessorKey: "stale_at", cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
    { header: t("Delivered"), accessorKey: "delivered_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) },
    { id: "actions", header: "", cell: ({ row }) => admin ? <span className="flex justify-end"><Button size="sm" variant="outline" onClick={() => resend.mutate(row.original)} disabled={resend.isPending}><RotateCcw className="size-4" /> {t("Resend corrected")}</Button></span> : null },
  ];
  const pendingJobs = (jobs.data?.items ?? []).filter((j) => j.status === "pending");
  const s = summary.data;
  return (
    <>
      <PageHeader title={t("Curation")} description={t("Controlled, reversible corrections on canonical records; the original values and every decision stay on file")} actions={admin && <Button onClick={() => setNewJob(true)}><Plus className="size-4" /> {t("New bulk job")}</Button>} />
      <Page>
        {s && (
          <div className="grid gap-3 sm:grid-cols-4">
            <Card><CardHeader className="pb-1"><CardTitle className="text-sm">{t("Pending")}</CardTitle></CardHeader><CardContent className="text-2xl">{s.pending_corrections + (s.jobs.pending ?? 0)}</CardContent></Card>
            <Card><CardHeader className="pb-1"><CardTitle className="text-sm">{t("Active corrections")}</CardTitle></CardHeader><CardContent className="text-2xl">{s.active_corrections}</CardContent></Card>
            <Card><CardHeader className="pb-1"><CardTitle className="text-sm">{t("Bulk jobs")}</CardTitle></CardHeader><CardContent className="text-2xl">{Object.values(s.jobs).reduce((a, b) => a + b, 0)}</CardContent></Card>
            <Card><CardHeader className="pb-1"><CardTitle className="text-sm">{t("Stale deliveries")}</CardTitle></CardHeader><CardContent className="text-2xl">{s.stale_deliveries}</CardContent></Card>
          </div>
        )}
        {s?.requires_approval && <Callout kind="info">{t("This project requires approval: corrections and jobs proposed by one person are applied after another person approves them.")}</Callout>}
        <Tabs value={tab} onValueChange={(v) => setParams((p) => { p.set("tab", v); return p; }, { replace: true })}><TabsList>{TABS.map(([t, label]) => <TabsTrigger key={t} value={t}>{label}</TabsTrigger>)}</TabsList></Tabs>
        {(corrections.error ?? jobs.error ?? stale.error) && <Callout kind="error">{(corrections.error ?? jobs.error ?? stale.error)?.message}</Callout>}
        {tab === "pending" && (
          <div className="space-y-4">
            {pendingJobs.length > 0 && <DataTable columns={jobColumns} data={pendingJobs} isLoading={false} onRowClick={setJob} footer="Bulk jobs waiting for approval" />}
            <DataTable columns={correctionColumns} data={corrections.data?.items} isLoading={corrections.isPending} emptyMessage={t("Nothing waits for approval.")} />
          </div>
        )}
        {(tab === "applied") && <DataTable columns={correctionColumns} data={corrections.data?.items} isLoading={corrections.isPending} emptyMessage={t("No active corrections.")} footer={corrections.data && `${corrections.data.items.length} corrections, newest first`} />}
        {tab === "reverted" && <DataTable columns={correctionColumns} data={[...(corrections.data?.items ?? []), ...(superseded.data?.items ?? [])].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))} isLoading={corrections.isPending || superseded.isPending} emptyMessage={t("No reverted or superseded corrections.")} />}
        {tab === "jobs" && <DataTable columns={jobColumns} data={jobs.data?.items} isLoading={jobs.isPending} emptyMessage={t("No bulk jobs yet.")} onRowClick={setJob} />}
        {tab === "impact" && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{t("Outbound deliveries whose object was corrected after it reached the target (architecture 28.10). Resend delivers the corrected version as a new delivery; nothing is sent without review. Rule replays requested on bulk jobs are shown in the job's detail.")}</p>
            <DataTable columns={staleColumns} data={stale.data?.items} isLoading={stale.isPending} emptyMessage={t("No stale deliveries.")} />
          </div>
        )}
      </Page>
      <RecordHistoryDialog projectId={projectId} target={history} onClose={() => setHistory(null)} />
      <Dialog open={reverting !== null} onOpenChange={(o) => !o && setReverting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>{t("Revert")} {reverting?.kind === "job" ? "the bulk job" : "the correction"}?</DialogTitle><DialogDescription>{t("The value before the correction comes back; the correction stays on file as reverted.")}</DialogDescription></DialogHeader>
          <Field label={t("Comment")} htmlFor="revert-comment"><Textarea id="revert-comment" rows={2} value={revertComment} onChange={(e) => setRevertComment(e.target.value)} /></Field>
          <DialogFooter><Button variant="outline" onClick={() => setReverting(null)}>{t("Cancel")}</Button><Button onClick={() => reverting && revert.mutate(reverting)} disabled={revert.isPending}>{t("Revert")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <NewJobDialog projectId={projectId} open={newJob} onOpenChange={setNewJob} onCreated={(j) => { setNewJob(false); void jobs.refetch(); void summary.refetch(); setJob(j); }} reasons={s?.reasons ?? Object.keys(REASON_LABELS)} />
      <JobDialog projectId={projectId} job={job} admin={admin} userId={user?.id ?? null} onClose={() => setJob(null)} onChanged={(j) => { setJob(j); invalidateAll(); }} onRevert={(j) => { setJob(null); setReverting({ kind: "job", id: j.id }); }} />
    </>
  );
}

function NewJobDialog({ projectId, open, onOpenChange, onCreated, reasons }: { projectId: string; open: boolean; onOpenChange: (o: boolean) => void; onCreated: (job: CurationJob) => void; reasons: string[] }) {
  const { t } = useTranslation();
  const [targetType, setTargetType] = useState<"position" | "measurement">("position");
  const [deviceIds, setDeviceIds] = useState<string[]>([]);
  const [entityIds, setEntityIds] = useState<string[]>([]);
  const [metricKeys, setMetricKeys] = useState<string[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [kind, setKind] = useState("time_offset");
  const [hours, setHours] = useState("12");
  const [valid, setValid] = useState(false);
  const [delta, setDelta] = useState("0");
  const [factor, setFactor] = useState("1");
  const [reason, setReason] = useState("DEVICE_FIRMWARE_BUG");
  const [comment, setComment] = useState("");
  const [replay, setReplay] = useState(false);
  const devices = useQuery({ queryKey: queryKeys.devices({ project: projectId, curation: true }), queryFn: () => api.get<PageType<Device>>("/api/v1/devices", { query: { project_id: projectId, limit: 500 } }), enabled: open });
  const entities = useQuery({ queryKey: queryKeys.entities(projectId), queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }), enabled: open });
  const metrics = useQuery({ queryKey: queryKeys.analyticsMetrics(projectId, { curation: true }), queryFn: () => api.get<MetricWithData[]>(`/api/v1/projects/${projectId}/analytics/metrics`, { query: { from: "2000-01-01T00:00:00Z" } }), enabled: open && targetType === "measurement" });
  const create = useMutationToast({
    mutationFn: () => api.post<CurationJob>(`/api/v1/projects/${projectId}/curation/jobs`, { body: {
      target_type: targetType, device_ids: deviceIds, entity_ids: entityIds, metric_keys: targetType === "measurement" ? metricKeys : [],
      time_from: new Date(from).toISOString(), time_to: new Date(to).toISOString(),
      transformation: { kind, seconds: kind === "time_offset" ? Math.round(Number(hours) * 3600) : 0, valid, delta: Number(delta), factor: Number(factor) },
      reason_code: reason, comment: comment || null, replay_rules: replay,
    } }),
    onSuccess: (j) => { toast.success(`Preview ready: ${j.affected_count} records`); onCreated(j); },
  });
  const kinds = targetType === "measurement" ? Object.keys(KINDS) : ["time_offset", "set_valid"];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>{t("New bulk correction")}</DialogTitle><DialogDescription>{t("Select records and one transformation; the preview shows what changes before anything is applied (architecture 28.5).")}</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <Field label={t("Records")} htmlFor="job-target">
            <Select value={targetType} onValueChange={(v) => { setTargetType(v as "position" | "measurement"); setKind("time_offset"); }}>
              <SelectTrigger id="job-target"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="position">{t("positions")}</SelectItem><SelectItem value="measurement">{t("measurements")}</SelectItem></SelectContent>
            </Select>
          </Field>
          <Field label={t("Devices")} htmlFor="job-devices" hint={t("Empty means every device of the project")}><MultiSelect options={(devices.data?.items ?? []).map((d) => ({ value: d.id, label: d.name }))} value={deviceIds} onChange={setDeviceIds} placeholder={t("All devices")} label={t("devices")} className="w-full" /></Field>
          <Field label={t("Entities")} htmlFor="job-entities" hint={t("Optional narrowing")}><MultiSelect options={(entities.data?.items ?? []).map((e) => ({ value: e.id, label: e.name }))} value={entityIds} onChange={setEntityIds} placeholder={t("Any entity")} label={t("entities")} className="w-full" /></Field>
          {targetType === "measurement" && <Field label={t("Metrics")} htmlFor="job-metrics"><MultiSelect options={(metrics.data ?? []).map((m) => ({ value: m.key, label: m.label })) } value={metricKeys} onChange={setMetricKeys} placeholder={t("All metrics")} label={t("metrics")} className="w-full" /></Field>}
          <div className="grid grid-cols-2 gap-2"><Field label={t("From (effective time, local)")} htmlFor="job-from"><Input id="job-from" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></Field><Field label={t("To")} htmlFor="job-to"><Input id="job-to" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></Field></div>
          <Field label={t("Transformation")} htmlFor="job-kind">
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger id="job-kind"><SelectValue /></SelectTrigger>
              <SelectContent>{kinds.map((k) => <SelectItem key={k} value={k}>{KINDS[k]}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          {kind === "time_offset" && <Field label={t("Hours to add (negative subtracts)")} htmlFor="job-hours"><Input id="job-hours" type="number" step="any" value={hours} onChange={(e) => setHours(e.target.value)} /></Field>}
          {kind === "set_valid" && <div className="flex items-center gap-2"><Switch id="job-valid" checked={valid} onCheckedChange={setValid} /><label htmlFor="job-valid">{valid ? "Mark valid" : "Mark invalid (hidden from every normal view)"}</label></div>}
          {kind === "value_offset" && <Field label={t("Add to every value")} htmlFor="job-delta"><Input id="job-delta" type="number" step="any" value={delta} onChange={(e) => setDelta(e.target.value)} /></Field>}
          {kind === "value_scale" && <Field label={t("Multiply every value by")} htmlFor="job-factor"><Input id="job-factor" type="number" step="any" value={factor} onChange={(e) => setFactor(e.target.value)} /></Field>}
          <Field label={t("Reason")} htmlFor="job-reason">
            <Select value={reason} onValueChange={setReason}>
              <SelectTrigger id="job-reason"><SelectValue /></SelectTrigger>
              <SelectContent>{reasons.map((r) => <SelectItem key={r} value={r}>{REASON_LABELS[r] ?? r}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label={t("Comment or evidence")} htmlFor="job-comment"><Textarea id="job-comment" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
          <div className="flex items-center gap-2"><Switch id="job-replay" checked={replay} onCheckedChange={setReplay} /><label htmlFor="job-replay" className="text-sm">{t("After applying, replay the enabled rules over the corrected window as a report")}</label></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>{t("Cancel")}</Button><Button disabled={!from || !to || create.isPending} onClick={() => create.mutate()}>{create.isPending ? "Previewing…" : "Preview"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function JobDialog({ projectId, job, admin, userId, onClose, onChanged, onRevert }: { projectId: string; job: CurationJob | null; admin: boolean; userId: string | null; onClose: () => void; onChanged: (job: CurationJob) => void; onRevert: (job: CurationJob) => void }) {
  const { t } = useTranslation();
  const base = `/api/v1/projects/${projectId}/curation/jobs`;
  const live = useQuery({ queryKey: queryKeys.curationJob(projectId, job?.id ?? ""), queryFn: () => api.get<CurationJob>(`${base}/${job?.id}`), enabled: job !== null, initialData: job ?? undefined, refetchInterval: (q) => (["applying", "reverting"].includes(q.state.data?.status ?? "") ? 2_000 : false) });
  const j = live.data ?? job;
  const act = useMutationToast({ mutationFn: (action: "apply" | "approve") => api.post<CurationJob>(`${base}/${job?.id}/${action}`), onSuccess: (updated) => { toast.success(updated.status === "pending" ? "Proposed; waits for approval" : "Applying in the background"); onChanged(updated); } });
  if (!j) return null;
  const preview = j.preview as { count?: number; transformation?: string; samples?: Array<Record<string, unknown>>; impact?: Record<string, unknown> };
  const impact = j.impact as { applied?: number; deliveries_flagged?: number; devices?: number; replay?: { rules: Array<Record<string, unknown>> } };
  const samples = preview.samples ?? [];
  const field = String((j.preview as { field?: string }).field ?? "time");
  return (
    <Dialog open={job !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader><DialogTitle className="flex items-center gap-2">{t("Bulk job")} <StatusBadge value={j.status} /></DialogTitle><DialogDescription>{`${t("{{type}}s", { type: j.target_type })}, ${describeTransformation(j.transformation as Record<string, unknown>)}, ${REASON_LABELS[j.reason_code] ?? j.reason_code}${j.comment ? `: ${j.comment}` : ""}`}</DialogDescription></DialogHeader>
        <div className="space-y-3 text-sm">
          {j.error_message && <Callout kind="error">{j.error_message}</Callout>}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div><span className="text-muted-foreground">{t("Affected")}</span><div className="text-lg">{j.affected_count}</div></div>
            <div><span className="text-muted-foreground">{t("Attribution changes")}</span><div className="text-lg">{String(preview.impact?.attribution_changes ?? 0)}{preview.impact?.estimated ? "+" : ""}</div></div>
            <div><span className="text-muted-foreground">{t("Sent deliveries")}</span><div className="text-lg">{String(preview.impact?.deliveries_sent ?? 0)}{preview.impact?.estimated ? "+" : ""}</div></div>
            <div><span className="text-muted-foreground">{t("Enabled rules")}</span><div className="text-lg">{String(preview.impact?.enabled_rules ?? 0)}</div></div>
          </div>
          {Boolean(preview.impact?.estimated) && <p className="text-xs text-muted-foreground">{t("Impact counted on the first")} {String(preview.impact?.scanned)} {t("records of")} {j.affected_count}.</p>}
          <div>
            <div className="mb-1 font-medium">{t("Samples")}</div>
            <table className="w-full text-xs"><thead><tr className="text-left text-muted-foreground"><th className="py-1">{t("Record")}</th><th>{t("Effective time")}</th><th>{t("Before")}</th><th>{t("After")}</th></tr></thead>
              <tbody>{samples.map((s) => <tr key={String(s.target_id)} className="border-t"><td className="py-1">{String(s.target_id)}{s.metric_key ? ` ${String(s.metric_key)}` : ""}</td><td>{formatTime(String(s.effective_time))}</td><td>{formatValue(field, s.before)}</td><td>{formatValue(field, s.after)}</td></tr>)}</tbody>
            </table>
          </div>
          <div className="text-xs text-muted-foreground">{t("Period {{from}} to {{to}}; {{devices}} devices", { from: formatTime(j.time_from), to: formatTime(j.time_to), devices: j.device_ids.length || t("all") })}{j.entity_ids.length ? t(", {{count}} entities", { count: j.entity_ids.length }) : ""}{j.metric_keys.length ? t(", metrics {{metrics}}", { metrics: j.metric_keys.join(", ") }) : ""}{t(". Created {{time}}", { time: formatTime(j.created_at) })}{j.approved_at ? t(", approved {{time}}", { time: formatTime(j.approved_at) }) : ""}{j.applied_at ? t(", applied {{time}}", { time: formatTime(j.applied_at) }) : ""}{j.reverted_at ? t(", reverted {{time}}", { time: formatTime(j.reverted_at) }) : ""}.</div>
          {(j.status === "applied" || j.status === "reverted") && (
            <div className="rounded-md border p-2 text-xs">
              <div>{impact.applied ?? j.applied_count} {t("corrections applied on")} {impact.devices ?? "?"} {t("devices;")} {impact.deliveries_flagged ?? 0} {t("outbound deliveries flagged stale")}{j.reverted_count ? `; ${j.reverted_count} reverted` : ""}.</div>
              {impact.replay && (
                <div className="mt-1">
                  <div className="font-medium">{t("Rule replay over the corrected window")}</div>
                  {impact.replay.rules.length === 0 && <div className="text-muted-foreground">{t("No enabled rule with a matching trigger.")}</div>}
                  <ul>{impact.replay.rules.map((r) => <li key={String(r.rule)}>{String(r.rule)}: {r.error ? String(r.error) : `${String(r.events)} events would fire over ${String(r.samples)} samples${r.truncated ? " (truncated)" : ""}`}</li>)}</ul>
                </div>
              )}
            </div>
          )}
          {(j.status === "applying" || j.status === "reverting") && <p className="text-muted-foreground">{j.status === "applying" ? `Applying: ${j.applied_count} of ${j.affected_count}` : `Reverting: ${j.reverted_count}`}…</p>}
          <details><summary className="cursor-pointer text-xs text-muted-foreground">{t("Raw preview and impact")}</summary><JsonView value={{ preview: j.preview, impact: j.impact }} className="mt-1 max-h-60" /></details>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("Close")}</Button>
          {admin && (j.status === "previewed" || j.status === "failed") && j.affected_count > 0 && <Button onClick={() => act.mutate("apply")} disabled={act.isPending}>{t("Apply to")} {j.affected_count} {t("records")}</Button>}
          {admin && j.status === "pending" && j.created_by_user_id !== userId && <Button onClick={() => act.mutate("approve")} disabled={act.isPending}><Check className="size-4" /> {t("Approve and apply")}</Button>}
          {admin && (j.status === "applied" || j.status === "pending" || j.status === "failed") && <Button variant="ghost" onClick={() => onRevert(j)}><Undo2 className="size-4" /> {t("Revert")}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
