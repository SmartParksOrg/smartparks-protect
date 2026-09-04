import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import * as maplibregl from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Alert, CurrentState, Entity, EventItem, MetricWithData, Page as PageType, SavedView, SeriesResponse } from "@/api/types";
import { SeriesChart } from "@/components/analytics/SeriesChart";
import { StatusBadge } from "@/components/common/StatusBadge";
import { loadBasemap } from "@/components/map/basemap";
import { ensureEntityLayers, setEntities } from "@/components/map/layers";
import { useMap } from "@/components/map/useMap";
import { type Aggregate, AGGREGATES, browserTimezone, CHART_TYPES, type ChartType, RANGE_PRESETS, type RangePreset, rangeFor, seriesLabel } from "@/lib/analytics";
import { formatAgo, formatTime } from "@/lib/format";

interface CurrentFeature { geometry: { coordinates: [number, number] }; properties: { entity_id: string; name: string; status: string; entity_type: string; active_alert_count?: number } }

/** A saved Data Explorer view as a chart (decision D86): the view's parameters become the same
 * series query the explorer runs. */
export function SavedViewTile({ projectId, view }: { projectId: string; view: SavedView }) {
  const { t } = useTranslation();
  const params = view.view as Record<string, string[]>;
  const metricsWanted = params.metric ?? [];
  const entityIds = params.entity ?? [];
  const range = ((params.range?.[0] ?? "7d") in RANGE_PRESETS ? params.range?.[0] ?? "7d" : "7d") as RangePreset;
  const bucket = params.bucket?.[0] ?? "auto";
  const aggregates = (params.agg ?? []).filter((a): a is Aggregate => (AGGREGATES as readonly string[]).includes(a));
  const chart = ((CHART_TYPES as readonly string[]).includes(params.chart?.[0] ?? "") ? params.chart?.[0] : "line") as ChartType;
  const timezone = params.tz?.[0] ?? browserTimezone();
  const window = useMemo(() => rangeFor(range), [range]);
  const query = useMemo(() => {
    const q = new URLSearchParams();
    for (const m of metricsWanted) q.append("metric", m);
    for (const e of entityIds) q.append("entity_id", e);
    q.set("from", window.from); q.set("to", window.to);
    if (bucket !== "auto") q.set("bucket", bucket);
    for (const a of aggregates.length ? aggregates : ["mean"]) q.append("agg", a);
    q.set("layout", "series");
    return q.toString();
  }, [metricsWanted, entityIds, window, bucket, aggregates]);
  const series = useQuery({ queryKey: queryKeys.analyticsSeries(projectId, { q: query, tile: view.id }), queryFn: () => api.get<SeriesResponse>(`/api/v1/projects/${projectId}/analytics/series?${query}`), enabled: metricsWanted.length > 0, refetchInterval: 60_000 });
  const entities = useQuery({ queryKey: queryKeys.entities(projectId), queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }) });
  const metrics = useQuery({ queryKey: queryKeys.analyticsMetrics(projectId, { range: "1y" }), queryFn: () => api.get<MetricWithData[]>(`/api/v1/projects/${projectId}/analytics/metrics`, { query: rangeFor("1y") }) });
  const names = useMemo(() => new Map((entities.data?.items ?? []).map((e) => [e.id, e.name])), [entities.data]);
  const metricLabels = useMemo(() => new Map((metrics.data ?? []).map((m) => [m.key, m.label])), [metrics.data]);
  const labels = useCallback((index: number) => (series.data?.series?.[index] ? seriesLabel(series.data.series[index], names, metricLabels) : ""), [series.data, names, metricLabels]);
  if (metricsWanted.length === 0) return <p className="text-sm text-muted-foreground">{t("This saved view has no metrics.")}</p>;
  if (series.isError) return <p className="text-sm text-destructive">{series.error.message}</p>;
  return (
    <div className="flex h-full flex-col">
      <SeriesChart response={series.data} type={chart} aggregate={aggregates[0] ?? "mean"} timezone={timezone} labels={labels} unit={metricsWanted.length === 1 ? metrics.data?.find((m) => m.key === metricsWanted[0])?.unit : null} className="min-h-48 flex-1" />
      <div className="mt-1 text-right text-xs text-muted-foreground"><Link className="underline" to={`/projects/${projectId}/analyze/explorer?view=${view.id}`}>{t("open in Data Explorer")}</Link></div>
    </div>
  );
}

/** Latest positions of the project's entities on a small map. */
export function MapTile({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const { mapRef, ready } = useMap(container, loadBasemap(), [31.5, -24.9], 6);
  const current = useQuery({ queryKey: queryKeys.currentState(projectId), queryFn: () => api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`), refetchInterval: 30_000 });
  const features = current.data?.features as unknown as CurrentFeature[] | undefined;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureEntityLayers(map, () => undefined, (lngLat, clusterId) => {
      const source = map.getSource("entities") as maplibregl.GeoJSONSource | undefined;
      void source?.getClusterExpansionZoom(clusterId).then((zoom) => map.easeTo({ center: lngLat, zoom }));
    });
  }, [mapRef, ready]);
  const fitted = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !features) return;
    void setEntities(map, features as unknown as GeoJSON.Feature[], null);
    if (!fitted.current && features.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const f of features) bounds.extend(f.geometry.coordinates);
      map.fitBounds(bounds, { padding: 30, maxZoom: 12, duration: 0 });
      fitted.current = true;
    }
  }, [mapRef, ready, features]);
  return (
    <div className="relative h-full min-h-64">
      <div ref={container} className="absolute inset-0 rounded-md" />
      <div className="absolute bottom-1 right-1 rounded bg-background/80 px-1 text-xs text-muted-foreground">{current.data ? `${current.data.total} entities` : ""} <Link className="underline" to={`/projects/${projectId}/map`}>{t("open map")}</Link></div>
    </div>
  );
}

/** Open alerts, newest first. */
export function AlertsTile({ projectId, limit = 8 }: { projectId: string; limit?: number }) {
  const { t } = useTranslation();
  const alerts = useQuery({ queryKey: queryKeys.alerts(projectId, { status: "open", limit, tile: true }), queryFn: () => api.get<PageType<Alert>>(`/api/v1/projects/${projectId}/alerts`, { query: { status: "open", limit } }), refetchInterval: 30_000 });
  if (alerts.isError) return <p className="text-sm text-destructive">{alerts.error.message}</p>;
  return (
    <ul className="divide-y text-sm">
      {alerts.data?.items.length === 0 && <li className="py-1 text-muted-foreground">{t("No open alerts.")}</li>}
      {alerts.data?.items.map((a) => <li key={a.id} className="flex flex-wrap items-center gap-2 py-1"><StatusBadge value={a.severity} /><Link className="min-w-0 flex-1 truncate underline-offset-2 hover:underline" to={`/projects/${projectId}/alerts?event=${a.event_id}`}>{a.title}</Link><span className="text-xs text-muted-foreground">{formatAgo(a.time)}</span></li>)}
    </ul>
  );
}

/** Recent events, newest first. */
export function EventsTile({ projectId, limit = 8 }: { projectId: string; limit?: number }) {
  const { t } = useTranslation();
  const events = useQuery({ queryKey: queryKeys.events(projectId, { limit, tile: true }), queryFn: () => api.get<PageType<EventItem>>(`/api/v1/projects/${projectId}/events`, { query: { limit } }), refetchInterval: 30_000 });
  if (events.isError) return <p className="text-sm text-destructive">{events.error.message}</p>;
  return (
    <ul className="divide-y text-sm">
      {events.data?.items.length === 0 && <li className="py-1 text-muted-foreground">{t("No events yet.")}</li>}
      {events.data?.items.map((e) => <li key={e.id} className="flex flex-wrap items-center gap-2 py-1"><StatusBadge value={e.severity} /><Link className="min-w-0 flex-1 truncate underline-offset-2 hover:underline" to={`/projects/${projectId}/rules/events?event=${e.id}`}>{e.title}</Link><span className="text-xs text-muted-foreground" title={formatTime(e.time)}>{formatAgo(e.time)}</span></li>)}
    </ul>
  );
}

/** Entities by status, and how many carry open alerts, from the current state. */
export function EntityStatusTile({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const current = useQuery({ queryKey: queryKeys.currentState(projectId), queryFn: () => api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`), refetchInterval: 60_000 });
  const features = (current.data?.features as unknown as CurrentFeature[] | undefined) ?? [];
  const byStatus = new Map<string, number>();
  let alerting = 0;
  for (const f of features) { byStatus.set(f.properties.status, (byStatus.get(f.properties.status) ?? 0) + 1); if ((f.properties.active_alert_count ?? 0) > 0) alerting += 1; }
  return (
    <div className="grid grid-cols-2 gap-2 text-sm">
      <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">{t("With a position")}</div><div className="text-2xl">{current.data?.total ?? "…"}</div></div>
      <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">{t("With open alerts")}</div><div className="text-2xl">{alerting}</div></div>
      {[...byStatus.entries()].map(([status, count]) => <div key={status} className="rounded-md border p-2"><div className="text-xs text-muted-foreground"><StatusBadge value={status} /></div><div className="text-2xl">{count}</div></div>)}
    </div>
  );
}
