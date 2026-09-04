import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Bookmark, ChartLine, Download, Trash2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Entity, MeasurementRow, MetricWithData, Page as PageType, SavedView, SeriesResponse } from "@/api/types";
import { ExportDialog } from "@/components/analytics/ExportDialog";
import { MultiSelect } from "@/components/analytics/MultiSelect";
import { SeriesChart } from "@/components/analytics/SeriesChart";
import { Callout } from "@/components/common/Callout";
import { EmptyState } from "@/components/common/EmptyState";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { CuratedBadge, CurateDialog, RecordHistoryDialog } from "@/components/curation/CurationDialogs";
import { SourceEventDialog, TraceDialog } from "@/components/devices/ProvenancePanel";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { type CurationTarget } from "@/lib/curation";
import { type Aggregate, AGGREGATES, browserTimezone, BUCKETS, bucketLabel, CHART_TYPES, type ChartType, formatInZone, type LongRow, RANGE_PRESETS, type RangePreset, rangeFor, seriesLabel, TIMEZONES, toLongRows } from "@/lib/analytics";
import { type ExportPreset } from "@/lib/exports";
import { useAuthStore } from "@/stores/auth";

/** Everything the explorer shows comes from the URL, so a view is a URL and a saved view is
 * its search parameters (decision D42). */
interface ExplorerState {
  metrics: string[];
  entities: string[];
  range: RangePreset;
  bucket: string;
  aggregates: Aggregate[];
  chart: ChartType;
  timezone: string;
}

function readState(params: URLSearchParams): ExplorerState {
  const agg = params.getAll("agg").filter((a): a is Aggregate => (AGGREGATES as readonly string[]).includes(a));
  const range = params.get("range") ?? "7d";
  const chart = params.get("chart") ?? "line";
  return {
    metrics: params.getAll("metric"),
    entities: params.getAll("entity"),
    range: (range in RANGE_PRESETS ? range : "7d") as RangePreset,
    bucket: params.get("bucket") ?? "auto",
    aggregates: agg.length ? agg : ["mean", "min", "max", "count"],
    chart: ((CHART_TYPES as readonly string[]).includes(chart) ? chart : "line") as ChartType,
    timezone: params.get("tz") ?? browserTimezone(),
  };
}

function writeState(state: ExplorerState): URLSearchParams {
  const params = new URLSearchParams();
  for (const m of state.metrics) params.append("metric", m);
  for (const e of state.entities) params.append("entity", e);
  params.set("range", state.range);
  if (state.bucket !== "auto") params.set("bucket", state.bucket);
  for (const a of state.aggregates) params.append("agg", a);
  params.set("chart", state.chart);
  params.set("tz", state.timezone);
  return params;
}

export function ExplorerPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const role = useProjectRole(projectId);
  const user = useAuthStore((s) => s.user);
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => readState(params), [params]);
  const update = useCallback((patch: Partial<ExplorerState>) => setParams(writeState({ ...readState(params), ...patch })), [params, setParams]);
  const [drill, setDrill] = useState<LongRow | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);

  const window = useMemo(() => rangeFor(state.range), [state.range]);
  const metrics = useQuery({ queryKey: queryKeys.analyticsMetrics(projectId, { range: "1y" }), queryFn: () => api.get<MetricWithData[]>(`/api/v1/projects/${projectId}/analytics/metrics`, { query: rangeFor("1y") }) });
  const entities = useQuery({ queryKey: queryKeys.entities(projectId), queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }) });
  const views = useQuery({ queryKey: queryKeys.savedViews(projectId), queryFn: () => api.get<PageType<SavedView>>(`/api/v1/projects/${projectId}/analytics/saved-views`, { query: { limit: 200 } }) });

  const seriesQuery = useMemo(() => {
    const q = new URLSearchParams();
    for (const m of state.metrics) q.append("metric", m);
    for (const e of state.entities) q.append("entity_id", e);
    q.set("from", window.from);
    q.set("to", window.to);
    if (state.bucket !== "auto") q.set("bucket", state.bucket);
    for (const a of state.aggregates) q.append("agg", a);
    q.set("layout", "series");
    return q.toString();
  }, [state, window]);
  const series = useQuery({
    queryKey: queryKeys.analyticsSeries(projectId, { q: seriesQuery }),
    queryFn: () => api.get<SeriesResponse>(`/api/v1/projects/${projectId}/analytics/series?${seriesQuery}`),
    enabled: state.metrics.length > 0,
    placeholderData: (previous) => previous,
  });

  const names = useMemo(() => new Map((entities.data?.items ?? []).map((e) => [e.id, e.name])), [entities.data]);
  const metricLabels = useMemo(() => new Map((metrics.data ?? []).map((m) => [m.key, m.label])), [metrics.data]);
  const labels = useCallback((index: number) => (series.data?.series?.[index] ? seriesLabel(series.data.series[index], names, metricLabels) : ""), [series.data, names, metricLabels]);
  const rows = useMemo(() => (series.data ? toLongRows(series.data, names) : []), [series.data, names]);
  const primary = state.aggregates[0] ?? "mean";
  const unit = state.metrics.length === 1 ? metrics.data?.find((m) => m.key === state.metrics[0])?.unit : null;

  const columns: ColumnDef<LongRow, unknown>[] = [
    { header: t("Time"), accessorKey: "time", cell: ({ getValue }) => formatInZone(getValue<string>(), state.timezone) },
    { header: t("Metric"), accessorKey: "metric_key", cell: ({ getValue }) => metricLabels.get(getValue<string>()) ?? getValue<string>() },
    { header: t("Entity"), accessorKey: "owner_name" },
    ...state.aggregates.map((a): ColumnDef<LongRow, unknown> => ({ id: a, header: a, accessorFn: (r) => r.values[a] ?? null, cell: ({ getValue }) => formatNumber(getValue<number | null>()) })),
  ];

  const saveView = useMutationToast({
    mutationFn: (name: string) => api.post<SavedView>(`/api/v1/projects/${projectId}/analytics/saved-views`, { body: { name, view: Object.fromEntries(Array.from(writeState(state).keys()).map((k) => [k, writeState(state).getAll(k)])), schema_version: 1 } }),
    invalidate: [queryKeys.savedViews(projectId)],
    success: t("View saved"),
    onSuccess: (view) => { setSaveOpen(false); setParams((p) => { p.set("view", view.id); return p; }); },
  });
  const deleteView = useMutationToast({
    mutationFn: (id: string) => api.delete<void>(`/api/v1/projects/${projectId}/analytics/saved-views/${id}`),
    invalidate: [queryKeys.savedViews(projectId)],
    success: t("View deleted"),
    onSuccess: () => setParams((p) => { p.delete("view"); return p; }),
  });
  const currentView = views.data?.items.find((v) => v.id === params.get("view"));

  function applyView(view: SavedView) {
    const next = new URLSearchParams();
    for (const [key, values] of Object.entries(view.view as Record<string, string[]>)) for (const v of values) next.append(key, v);
    next.set("view", view.id);
    setParams(next);
  }

  const exportPreset: ExportPreset = { dataset: "aggregates", metricKeys: state.metrics, entityIds: state.entities, from: window.from, to: window.to, bucket: state.bucket === "auto" ? undefined : state.bucket, aggregates: state.aggregates, timezone: state.timezone };

  return (
    <>
      <PageHeader
        title={t("Data explorer")}
        description={t("Server side aggregates of the project's measurements; drill down to the rows and source events behind a bucket")}
        actions={<>
          <Select value={currentView?.id ?? "none"} onValueChange={(id) => { const v = views.data?.items.find((x) => x.id === id); if (v) applyView(v); }}>
            <SelectTrigger className="w-48" aria-label={t("Saved views")}><SelectValue placeholder={t("Saved views")} /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled>{views.data?.items.length ? "Saved views" : "No saved views yet"}</SelectItem>
              {views.data?.items.map((v) => <SelectItem key={v.id} value={v.id}>{v.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => setSaveOpen(true)} disabled={state.metrics.length === 0}><Bookmark className="size-4" /> {t("Save view")}</Button>
          {currentView && (currentView.created_by === user?.id || canAdmin(role)) && (
            <Button variant="outline" size="icon" aria-label={t("Delete saved view")} onClick={() => deleteView.mutate(currentView.id)}><Trash2 className="size-4" /></Button>
          )}
          <Button onClick={() => setExportOpen(true)} disabled={state.metrics.length === 0}><Download className="size-4" /> {t("Export")}</Button>
        </>}
      />
      <Page>
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Field label={t("Metrics")} htmlFor="metrics">
            <MultiSelect options={(metrics.data ?? []).map((m) => ({ value: m.key, label: m.label, hint: m.unit ?? undefined }))} value={state.metrics} onChange={(v) => update({ metrics: v })} placeholder={t("Choose metrics")} label={t("metrics")} className="w-full" maxSelected={20} />
          </Field>
          <Field label={t("Entities")} htmlFor="entities" hint={state.entities.length === 0 ? "All entities" : undefined}>
            <MultiSelect options={(entities.data?.items ?? []).map((e) => ({ value: e.id, label: e.name }))} value={state.entities} onChange={(v) => update({ entities: v })} placeholder={t("All entities")} label={t("entities")} className="w-full" maxSelected={20} />
          </Field>
          <Field label={t("Range")} htmlFor="range">
            <Select value={state.range} onValueChange={(v) => update({ range: v as RangePreset })}>
              <SelectTrigger id="range"><SelectValue /></SelectTrigger>
              <SelectContent>{Object.entries(RANGE_PRESETS).map(([k, p]) => <SelectItem key={k} value={k}>{p.label}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label={t("Bucket")} htmlFor="bucket" hint={series.data ? `${series.data.automatic_bucket ? "automatic, " : ""}${bucketLabel(series.data.bucket_seconds)}` : undefined}>
            <Select value={state.bucket} onValueChange={(v) => update({ bucket: v })}>
              <SelectTrigger id="bucket"><SelectValue /></SelectTrigger>
              <SelectContent>{BUCKETS.map((b) => <SelectItem key={b} value={b}>{b === "auto" ? "Automatic" : b === "all" ? "Whole range" : b}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label={t("Aggregates")} htmlFor="aggregates" hint={`Chart shows ${primary}`}>
            <MultiSelect options={AGGREGATES.map((a) => ({ value: a, label: a }))} value={state.aggregates} onChange={(v) => update({ aggregates: v.length ? (v as Aggregate[]) : ["mean"] })} placeholder={t("Aggregates")} label={t("aggregates")} className="w-full" />
          </Field>
          <Field label={t("Timezone")} htmlFor="tz">
            <Select value={state.timezone} onValueChange={(v) => update({ timezone: v })}>
              <SelectTrigger id="tz"><SelectValue /></SelectTrigger>
              <SelectContent>{[...new Set([browserTimezone(), ...TIMEZONES])].map((z) => <SelectItem key={z} value={z}>{z}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
        </div>

        {state.metrics.length === 0 ? (
          <EmptyState icon={ChartLine} title={t("Choose a metric to start")} description={t("Metrics with data in the last year are listed. Pick entities to compare, or leave the field empty for the whole project.")} />
        ) : (
          <>
            {series.error && <Callout kind="error">{series.error.message}</Callout>}
            <div className="rounded-md border p-2">
              <Tabs value={state.chart} onValueChange={(v) => update({ chart: v as ChartType })}>
                <TabsList>{CHART_TYPES.map((t) => <TabsTrigger key={t} value={t} className="capitalize">{t === "state" ? "State timeline" : t}</TabsTrigger>)}</TabsList>
              </Tabs>
              <SeriesChart response={series.data} type={state.chart} aggregate={primary} timezone={state.timezone} labels={labels} unit={unit} />
            </div>
            <DataTable columns={columns} data={rows} isLoading={series.isPending} emptyMessage={t("No measurements in this range.")} onRowClick={setDrill} footer={series.data && `${rows.length} rows, ${series.data.series?.length ?? 0} series, bucket ${bucketLabel(series.data.bucket_seconds)}`} />
          </>
        )}
      </Page>
      <DrillDownDialog projectId={projectId} row={drill} bucketSeconds={series.data?.bucket_seconds ?? 0} timezone={state.timezone} onClose={() => setDrill(null)} canCurate={canAdmin(role)} />
      <ExportDialog projectId={projectId} open={exportOpen} onOpenChange={setExportOpen} preset={exportPreset} />
      <SaveViewDialog open={saveOpen} onOpenChange={setSaveOpen} onSave={(name) => saveView.mutate(name)} pending={saveView.isPending} />
    </>
  );
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}

/** The normalized rows behind one bucket, each linking to its source event. */
function DrillDownDialog({ projectId, row, bucketSeconds, timezone, onClose, canCurate }: { projectId: string; row: LongRow | null; bucketSeconds: number; timezone: string; onClose: () => void; canCurate: boolean }) {
  const { t } = useTranslation();
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(null);
  const [trace, setTrace] = useState<string | null>(null);
  const [curating, setCurating] = useState<CurationTarget | null>(null);
  const [history, setHistory] = useState<CurationTarget | null>(null);
  const from = row?.time;
  const to = row ? new Date(new Date(row.time).getTime() + Math.max(bucketSeconds, 1) * 1000).toISOString() : undefined;
  const rows = useQuery({
    queryKey: queryKeys.analyticsRows(projectId, { metric: row?.metric_key, owner: row?.owner_id, from, to }),
    queryFn: () => api.get<PageType<MeasurementRow>>(`/api/v1/projects/${projectId}/analytics/rows`, { query: { metric: row?.metric_key, entity_id: row?.owner_id ?? undefined, from, to, limit: 500 } }),
    enabled: row !== null,
  });
  const columns: ColumnDef<MeasurementRow, unknown>[] = [
    { header: t("Time"), accessorKey: "time", cell: ({ getValue }) => formatInZone(getValue<string>(), timezone, { timeStyle: "medium" }) },
    { header: t("Value"), accessorKey: "value", cell: ({ getValue, row: r }) => { const v = getValue<unknown>(); return <span className="inline-flex items-center gap-1">{typeof v === "number" ? formatNumber(v) : JSON.stringify(v)}<CuratedBadge curatedFields={r.original.curated_fields ?? []} valid={r.original.valid ?? true} onClick={() => setHistory({ target_type: "measurement", target_id: r.original.id, target_time: r.original.original_time })} /></span>; } },
    { header: t("Device"), accessorKey: "device_id", cell: ({ getValue }) => getValue<string>().slice(0, 8) },
    { header: t("Source event"), accessorKey: "source_event_id", cell: ({ row: r }) => (r.original.source_event_id ? <Button variant="link" size="sm" className="h-auto p-0" onClick={(e) => { e.stopPropagation(); setEvent({ id: r.original.source_event_id!, ingestedAt: r.original.source_event_ingested_at! }); }}>{t("open")}</Button> : "") },
    { header: t("Trace"), accessorKey: "trace_id", cell: ({ row: r }) => (r.original.trace_id ? <Button variant="link" size="sm" className="h-auto p-0" onClick={(e) => { e.stopPropagation(); setTrace(r.original.trace_id!); }}>{t("view")}</Button> : "") },
    ...(canCurate ? [{ id: "curate", header: "", cell: ({ row: r }: { row: { original: MeasurementRow } }) => <Button variant="link" size="sm" className="h-auto p-0" onClick={(e) => { e.stopPropagation(); setCurating({ target_type: "measurement", target_id: r.original.id, target_time: r.original.original_time }); }}>{t("curate")}</Button> } as ColumnDef<MeasurementRow, unknown>] : []),
  ];
  return (
    <>
      <Dialog open={row !== null} onOpenChange={(o) => !o && onClose()}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("Rows behind the bucket")}</DialogTitle>
            <DialogDescription>{row && `${row.metric_key}${row.owner_name ? ` · ${row.owner_name}` : ""}, from ${formatInZone(row.time, timezone)} for ${bucketLabel(bucketSeconds)}`}</DialogDescription>
          </DialogHeader>
          <DataTable columns={columns} data={rows.data?.items} isLoading={rows.isPending} emptyMessage={t("No rows.")} footer={rows.data?.next_cursor ? "Showing the first 500 rows" : undefined} />
        </DialogContent>
      </Dialog>
      <SourceEventDialog id={event?.id ?? null} ingestedAt={event?.ingestedAt ?? null} onClose={() => setEvent(null)} />
      <TraceDialog traceId={trace} onClose={() => setTrace(null)} />
      <CurateDialog projectId={projectId} target={curating} onClose={() => { setCurating(null); void rows.refetch(); }} />
      <RecordHistoryDialog projectId={projectId} target={history} onClose={() => setHistory(null)} />
    </>
  );
}

function SaveViewDialog({ open, onOpenChange, onSave, pending }: { open: boolean; onOpenChange: (o: boolean) => void; onSave: (name: string) => void; pending: boolean }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{t("Save this view")}</DialogTitle><DialogDescription>{t("Metrics, entities, range, bucket, aggregates and chart, shared with the project.")}</DialogDescription></DialogHeader>
        <Field label={t("Name")} htmlFor="view-name"><Input id="view-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("Battery, last 30 days")} /></Field>
        <DialogFooter><Button onClick={() => onSave(name.trim())} disabled={!name.trim() || pending}>{t("Save")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
