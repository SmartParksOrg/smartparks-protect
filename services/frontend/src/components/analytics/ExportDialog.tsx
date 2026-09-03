import { useQuery } from "@tanstack/react-query";
import { Download, ListPlus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api, downloadFile } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Entity, ExportJob, MetricWithData, Page } from "@/api/types";
import { MultiSelect } from "@/components/analytics/MultiSelect";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { type Aggregate, AGGREGATES, BUCKETS, browserTimezone, RANGE_PRESETS, type RangePreset, rangeFor, TIMEZONES } from "@/lib/analytics";
import { type Dataset, DATASETS, directExportQuery, type ExportPreset } from "@/lib/exports";

interface Props {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preset?: ExportPreset;
}

/** One form for both paths: download now (bounded) or queue a job for the export service. The
 * form remounts on every open, so the preset is read once as initial state. */
export function ExportDialog({ projectId, open, onOpenChange, preset }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Export</DialogTitle>
          <DialogDescription>Download up to 100,000 rows at once, or queue a job for anything larger. Times are written in the chosen timezone.</DialogDescription>
        </DialogHeader>
        {open && <ExportForm projectId={projectId} preset={preset} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function ExportForm({ projectId, preset, onDone }: { projectId: string; preset?: ExportPreset; onDone: () => void }) {
  const [dataset, setDataset] = useState<Dataset>(preset?.dataset ?? "positions");
  const [chosenFormat, setFormat] = useState(preset?.format ?? "csv");
  const [range, setRange] = useState<RangePreset | "custom">(preset?.from && preset.to ? "custom" : preset?.range ?? "7d");
  const [from, setFrom] = useState(preset?.from?.slice(0, 16) ?? "");
  const [to, setTo] = useState(preset?.to?.slice(0, 16) ?? "");
  const [entityIds, setEntityIds] = useState<string[]>(preset?.entityIds ?? []);
  const [metricKeys, setMetricKeys] = useState<string[]>(preset?.metricKeys ?? []);
  const [bucket, setBucket] = useState(preset?.bucket ?? "auto");
  const [aggregates, setAggregates] = useState<Aggregate[]>(preset?.aggregates ?? ["mean", "min", "max", "count"]);
  const [layout, setLayout] = useState<"long" | "wide">(preset?.layout ?? "long");
  const [timezone, setTimezone] = useState(preset?.timezone ?? browserTimezone());
  const [includeNames, setIncludeNames] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const formats = DATASETS[dataset].formats as readonly string[];
  const format = formats.includes(chosenFormat) ? chosenFormat : formats[0];

  const entities = useQuery({ queryKey: queryKeys.entities(projectId), queryFn: () => api.get<Page<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }) });
  const metrics = useQuery({ queryKey: queryKeys.analyticsMetrics(projectId, { range: "1y" }), queryFn: () => api.get<MetricWithData[]>(`/api/v1/projects/${projectId}/analytics/metrics`, { query: rangeFor("1y") }) });

  function parameters(): Record<string, unknown> | null {
    const window = range === "custom" ? { from: from ? new Date(from).toISOString() : "", to: to ? new Date(to).toISOString() : "" } : rangeFor(range);
    if (!window.from || !window.to) {
      setError("Give a start and an end");
      return null;
    }
    if (dataset === "aggregates" && metricKeys.length === 0) {
      setError("Aggregates need at least one metric");
      return null;
    }
    return {
      dataset,
      format,
      time_from: window.from,
      time_to: window.to,
      entity_ids: dataset === "source_events" ? [] : entityIds,
      metric_keys: dataset === "positions" || dataset === "source_events" ? [] : metricKeys,
      timezone,
      include_names: includeNames,
      ...(dataset === "aggregates" ? { bucket: bucket === "auto" ? null : bucket, aggregates, layout } : {}),
    };
  }

  const queue = useMutationToast({
    mutationFn: (body: Record<string, unknown>) => api.post<ExportJob>(`/api/v1/projects/${projectId}/exports`, { body }),
    invalidate: [queryKeys.exports(projectId)],
    success: "Export queued; it appears under Exports when done",
    onSuccess: onDone,
    onError: (e) => setError(e.message),
  });

  async function downloadNow() {
    const params = parameters();
    if (!params) return;
    setError(null);
    setDownloading(true);
    try {
      await downloadFile(`/api/v1/projects/${projectId}/exports/direct?${directExportQuery(params)}`, `${dataset}.${format}`);
      onDone();
    } catch (e) {
      const message = (e as Error).message;
      setError(message);
      if (message.includes("export job")) toast.info("Too large to download at once, queue it as a job instead");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Data" htmlFor="dataset">
          <Select value={dataset} onValueChange={(v) => setDataset(v as Dataset)}>
            <SelectTrigger id="dataset"><SelectValue /></SelectTrigger>
            <SelectContent>{Object.entries(DATASETS).map(([k, d]) => <SelectItem key={k} value={k}>{d.label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Format" htmlFor="format">
          <Select value={format} onValueChange={setFormat}>
            <SelectTrigger id="format"><SelectValue /></SelectTrigger>
            <SelectContent>{formats.map((f) => <SelectItem key={f} value={f}>{f.toUpperCase()}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Range" htmlFor="range">
          <Select value={range} onValueChange={(v) => setRange(v as RangePreset | "custom")}>
            <SelectTrigger id="range"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(RANGE_PRESETS).map(([k, p]) => <SelectItem key={k} value={k}>{p.label}</SelectItem>)}
              <SelectItem value="custom">Custom</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Timezone" htmlFor="timezone">
          <Select value={timezone} onValueChange={setTimezone}>
            <SelectTrigger id="timezone"><SelectValue /></SelectTrigger>
            <SelectContent>{[...new Set([browserTimezone(), ...TIMEZONES])].map((z) => <SelectItem key={z} value={z}>{z}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        {range === "custom" && (
          <>
            <Field label="From" htmlFor="from"><Input id="from" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To" htmlFor="to"><Input id="to" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </>
        )}
        {dataset !== "source_events" && (
          <Field label="Entities" htmlFor="entities" hint="Empty means every entity of the project">
            <MultiSelect options={(entities.data?.items ?? []).map((e) => ({ value: e.id, label: e.name }))} value={entityIds} onChange={setEntityIds} placeholder="All entities" label="entities" className="w-full" />
          </Field>
        )}
        {(dataset === "measurements" || dataset === "aggregates") && (
          <Field label="Metrics" htmlFor="metrics" hint={dataset === "aggregates" ? "Required" : "Empty means every metric"}>
            <MultiSelect options={(metrics.data ?? []).map((m) => ({ value: m.key, label: m.label, hint: m.unit ?? undefined }))} value={metricKeys} onChange={setMetricKeys} placeholder={dataset === "aggregates" ? "Choose metrics" : "All metrics"} label="metrics" className="w-full" />
          </Field>
        )}
        {dataset === "aggregates" && (
          <>
            <Field label="Bucket" htmlFor="bucket">
              <Select value={bucket} onValueChange={setBucket}>
                <SelectTrigger id="bucket"><SelectValue /></SelectTrigger>
                <SelectContent>{BUCKETS.map((b) => <SelectItem key={b} value={b}>{b === "auto" ? "Automatic" : b === "all" ? "Whole range" : b}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Aggregates" htmlFor="aggregates">
              <MultiSelect options={AGGREGATES.map((a) => ({ value: a, label: a }))} value={aggregates} onChange={(v) => setAggregates(v as Aggregate[])} placeholder="Choose aggregates" label="aggregates" className="w-full" />
            </Field>
            <Field label="Layout" htmlFor="layout">
              <Select value={layout} onValueChange={(v) => setLayout(v as "long" | "wide")}>
                <SelectTrigger id="layout"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="long">Long (one row per bucket and series)</SelectItem><SelectItem value="wide">Wide (one column per series)</SelectItem></SelectContent>
              </Select>
            </Field>
          </>
        )}
        <div className="flex items-center gap-2 sm:col-span-2">
          <Switch id="names" checked={includeNames} onCheckedChange={setIncludeNames} />
          <label htmlFor="names" className="text-sm">Include entity, device and metric names</label>
        </div>
      </div>
      {error && <Callout kind="error">{error}</Callout>}
      <DialogFooter className="gap-2 sm:justify-between">
        <Button variant="outline" onClick={() => void downloadNow()} disabled={downloading}><Download className="size-4" /> {downloading ? "Preparing…" : "Download now"}</Button>
        <Button onClick={() => { const p = parameters(); if (p) queue.mutate(p); }} disabled={queue.isPending}><ListPlus className="size-4" /> Queue as job</Button>
      </DialogFooter>
    </>
  );
}
