import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeliveryDetail, SourceEvent, Trace } from "@/api/types";
import { JsonView } from "@/components/common/JsonView";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { channelLabel, formatTime } from "@/lib/format";
import { useState } from "react";

/** Every delivery of one canonical record, with a filter on the acquisition channel
 * (architecture 25.7): the same fix over LoRaWAN, from a log file and over WebBLE is one row
 * with three deliveries. */
export function RecordDeliveries({ canonicalType, canonicalId, onOpenEvent }: { canonicalType: string; canonicalId: number; onOpenEvent?: (id: number, ingestedAt: string) => void }) {
  const [channel, setChannel] = useState<string>("all");
  const deliveries = useQuery({ queryKey: queryKeys.recordDeliveries(canonicalType, canonicalId), queryFn: () => api.get<DeliveryDetail[]>("/api/v1/deliveries", { query: { canonical_type: canonicalType, canonical_id: canonicalId } }) });
  if (deliveries.isPending) return <div className="text-sm text-muted-foreground">Loading deliveries…</div>;
  if (deliveries.isError) return <div className="text-sm text-destructive">{deliveries.error.message}</div>;
  const channels = [...new Set(deliveries.data.map((d) => d.acquisition_channel))];
  const rows = channel === "all" ? deliveries.data : deliveries.data.filter((d) => d.acquisition_channel === channel);
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-muted-foreground">{deliveries.data.length} {deliveries.data.length === 1 ? "delivery" : "deliveries"} of {canonicalType} {canonicalId}</span>
        {channels.length > 1 && (
          <span className="ml-auto flex gap-1">
            <Button size="sm" variant={channel === "all" ? "default" : "outline"} className="h-6 px-2 text-xs" onClick={() => setChannel("all")}>all</Button>
            {channels.map((c) => <Button key={c} size="sm" variant={channel === c ? "default" : "outline"} className="h-6 px-2 text-xs" onClick={() => setChannel(c)}>{channelLabel(c)}</Button>)}
          </span>
        )}
      </div>
      <ul className="divide-y">
        {rows.map((d) => (
          <li key={`${d.source_event_id}-${d.source_event_ingested_at}`} className="flex flex-wrap items-center gap-2 py-1">
            <Badge variant="outline">{channelLabel(d.acquisition_channel)}</Badge>
            <span>{d.data_source_name ?? d.data_source_id}</span>
            <span className="text-xs text-muted-foreground">
              {d.network_received_at ? `network ${formatTime(d.network_received_at)}` : d.satellite_delivered_at ? `satellite ${formatTime(d.satellite_delivered_at)}` : d.ble_synced_at ? `synced ${formatTime(d.ble_synced_at)}` : d.file_uploaded_at ? `uploaded ${formatTime(d.file_uploaded_at)}` : `ingested ${formatTime(d.source_event_ingested_at)}`}
            </span>
            {d.first ? <Badge variant="secondary">created the record</Badge> : <span className="text-xs text-muted-foreground">repeat delivery</span>}
            {onOpenEvent && <Button variant="link" size="sm" className="ml-auto h-auto p-0" onClick={() => onOpenEvent(d.source_event_id, d.source_event_ingested_at)}>source event {d.source_event_id}</Button>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Trace steps with status, timing and the structured error (architecture 26.3). */
export function TraceSteps({ traceId }: { traceId: string }) {
  const trace = useQuery({ queryKey: queryKeys.trace(traceId), queryFn: () => api.get<Trace>(`/api/v1/traces/${traceId}`) });
  if (trace.isPending) return <div className="text-sm text-muted-foreground">Loading trace…</div>;
  if (trace.isError) return <div className="text-sm text-destructive">{trace.error.message}</div>;
  const t = trace.data;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge value={t.status} />
        <Badge variant="outline">{t.trace_class}</Badge>
        <span className="text-muted-foreground">{t.root_object_type} {t.root_object_id}</span>
        <span className="text-muted-foreground">{formatTime(t.started_at)}</span>
        {t.compact && <Badge variant="secondary">compact</Badge>}
      </div>
      <TraceTimeline trace={t} />
      <ol className="space-y-1">
        {t.steps.map((step) => (
          <li key={step.sequence} className="rounded-md border px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge value={step.status} />
              <span className="font-medium">{step.component}</span>
              <span>{step.operation}</span>
              {step.duration_ms != null && <span className="ml-auto text-xs text-muted-foreground">{step.duration_ms} ms</span>}
            </div>
            {(step.input_ref || step.output_ref) && <div className="mt-1 text-xs text-muted-foreground">{step.input_ref && <span>in {step.input_ref} </span>}{step.output_ref && <span>out {step.output_ref}</span>}</div>}
            {step.error && (
              <div className="mt-2 rounded bg-destructive/10 p-2 text-xs">
                <div className="font-medium text-destructive">{step.error.error_code as string}: {step.error.message as string}</div>
                <div className="text-muted-foreground">{step.error.retryable ? "retryable" : "not retryable"}{step.error.user_actionable ? ", an administrator can fix this" : ""}</div>
              </div>
            )}
            {Object.keys(step.metadata ?? {}).length > 0 && <JsonView value={step.metadata} className="mt-2 max-h-40" />}
          </li>
        ))}
      </ol>
      {t.error && !t.steps.some((s) => s.error) && <div className="rounded bg-destructive/10 p-2 text-xs text-destructive">{t.error.error_code as string}: {t.error.message as string}</div>}
    </div>
  );
}

const stepTone: Record<string, string> = { success: "bg-primary", duplicate: "bg-brand-blue", skipped: "bg-muted-foreground/40", failed: "bg-destructive", dead_letter: "bg-destructive", retrying: "bg-brand-sand", processing: "bg-brand-green-light", pending: "bg-muted-foreground/40" };

/** The trace as a timeline (architecture 26.3): one bar per step, placed and sized by its start and
 * duration against the whole trace. Steps without a start are drawn at their sequence position. */
export function TraceTimeline({ trace }: { trace: Trace }) {
  const steps = trace.steps;
  if (steps.length === 0) return null;
  const start = new Date(trace.started_at).getTime();
  const ends = steps.map((s) => (s.completed_at ? new Date(s.completed_at).getTime() : s.started_at ? new Date(s.started_at).getTime() + (s.duration_ms ?? 0) : start));
  const total = Math.max(1, (trace.completed_at ? new Date(trace.completed_at).getTime() : Math.max(...ends)) - start);
  return (
    <div className="rounded-md border px-3 py-2">
      <div className="mb-1 flex justify-between text-[10px] text-muted-foreground"><span>0 ms</span><span>{total} ms</span></div>
      <ol className="space-y-0.5">
        {steps.map((step, index) => {
          const left = step.started_at ? Math.min(100, Math.max(0, ((new Date(step.started_at).getTime() - start) / total) * 100)) : (index / steps.length) * 100;
          const width = Math.max(0.8, Math.min(100 - left, ((step.duration_ms ?? 0) / total) * 100));
          return (
            <li key={step.sequence} className="flex items-center gap-2 text-xs">
              <span className="w-40 shrink-0 truncate text-muted-foreground" title={`${step.component} ${step.operation}`}>{step.sequence}. {step.operation}</span>
              <span className="relative h-2.5 flex-1 overflow-hidden rounded bg-muted">
                <span className={`absolute top-0 h-full rounded ${stepTone[step.status] ?? "bg-primary"}`} style={{ left: `${left}%`, width: `${width}%` }} title={`${step.status}${step.duration_ms != null ? `, ${step.duration_ms} ms` : ""}`} />
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Where a record came from: data source, identity, every delivery, raw payload, trace, deep links. */
export function SourceEventPanel({ id, ingestedAt }: { id: number; ingestedAt: string }) {
  const event = useQuery({ queryKey: queryKeys.sourceEvent(id, ingestedAt), queryFn: () => api.get<SourceEvent>(`/api/v1/source-events/${id}`, { query: { ingested_at: ingestedAt } }) });
  if (event.isPending) return <div className="text-sm text-muted-foreground">Loading source event…</div>;
  if (event.isError) return <div className="text-sm text-destructive">{event.error.message}</div>;
  const e = event.data;
  return (
    <Tabs defaultValue="provenance">
      <TabsList>
        <TabsTrigger value="provenance">Provenance</TabsTrigger>
        <TabsTrigger value="payload">Raw payload</TabsTrigger>
        {e.trace_id && <TabsTrigger value="trace">Trace</TabsTrigger>}
      </TabsList>
      <TabsContent value="provenance" className="space-y-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Data source</dt><dd>{e.data_source_name ?? e.data_source_id}</dd>
          <dt className="text-muted-foreground">External id</dt><dd className="font-mono">{e.external_id ?? "none"}</dd>
          <dt className="text-muted-foreground">Event type</dt><dd>{e.event_type}</dd>
          <dt className="text-muted-foreground">Channel</dt><dd>{channelLabel(e.acquisition_channel)} over {e.ingestion_method.replace("_", " ")}</dd>
          <dt className="text-muted-foreground">Network received</dt><dd>{formatTime(e.network_received_at) || "unknown"}</dd>
          {e.satellite_delivered_at && <><dt className="text-muted-foreground">Satellite session</dt><dd>{formatTime(e.satellite_delivered_at)}</dd></>}
          {e.ble_synced_at && <><dt className="text-muted-foreground">Read over BLE</dt><dd>{formatTime(e.ble_synced_at)}</dd></>}
          {e.file_uploaded_at && <><dt className="text-muted-foreground">File uploaded</dt><dd>{formatTime(e.file_uploaded_at)}</dd></>}
          <dt className="text-muted-foreground">Ingested</dt><dd>{formatTime(e.ingested_at)}</dd>
          <dt className="text-muted-foreground">Status</dt><dd><StatusBadge value={e.processing_status} /> {e.error_code}</dd>
        </dl>
        {e.links.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {e.links.map((link) => (
              <Button key={link.key} asChild variant="outline" size="sm"><a href={link.url} target="_blank" rel="noreferrer"><ExternalLink className="size-4" /> {link.label}</a></Button>
            ))}
          </div>
        )}
        <div>
          <div className="mb-1 text-sm font-medium">Deliveries linked to canonical rows</div>
          {e.deliveries.length === 0 ? <div className="text-sm text-muted-foreground">No canonical rows from this event.</div> : (
            <ul className="text-sm">
              {e.deliveries.map((d) => <li key={`${d.canonical_type}${d.canonical_id}`}>{d.canonical_type} {d.canonical_id} at {formatTime(d.canonical_time)} {d.first ? "(created by this delivery)" : "(repeat delivery)"}</li>)}
            </ul>
          )}
        </div>
        {e.deliveries.filter((d) => d.canonical_type === "position").slice(0, 3).map((d) => (
          <div key={`all-${d.canonical_id}`} className="rounded-md border p-2"><RecordDeliveries canonicalType="position" canonicalId={d.canonical_id} /></div>
        ))}
      </TabsContent>
      <TabsContent value="payload">
        {e.payload ? <JsonView value={e.payload} /> : <div className="text-sm text-muted-foreground">Payload stored out of line ({e.payload_size} bytes) as {e.payload_object_key}.</div>}
      </TabsContent>
      {e.trace_id && <TabsContent value="trace"><TraceSteps traceId={e.trace_id} /></TabsContent>}
    </Tabs>
  );
}

export function RecordDeliveriesDialog({ canonicalType, canonicalId, onClose, onOpenEvent }: { canonicalType: string; canonicalId: number | null; onClose: () => void; onOpenEvent?: (id: number, ingestedAt: string) => void }) {
  return (
    <Dialog open={canonicalId != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>Deliveries</DialogTitle><DialogDescription>Every path this record arrived over (architecture 25.7)</DialogDescription></DialogHeader>
        {canonicalId != null && <RecordDeliveries canonicalType={canonicalType} canonicalId={canonicalId} onOpenEvent={onOpenEvent} />}
      </DialogContent>
    </Dialog>
  );
}

export function SourceEventDialog({ id, ingestedAt, onClose }: { id: number | null; ingestedAt: string | null; onClose: () => void }) {
  return (
    <Dialog open={id != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>Source event {id}</DialogTitle><DialogDescription>Raw delivery and how it was processed</DialogDescription></DialogHeader>
        {id != null && ingestedAt && <SourceEventPanel id={id} ingestedAt={ingestedAt} />}
      </DialogContent>
    </Dialog>
  );
}

export function TraceDialog({ traceId, onClose }: { traceId: string | null; onClose: () => void }) {
  return (
    <Dialog open={traceId != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>Processing trace</DialogTitle><DialogDescription className="font-mono text-xs">{traceId}</DialogDescription></DialogHeader>
        {traceId && <TraceSteps traceId={traceId} />}
      </DialogContent>
    </Dialog>
  );
}
