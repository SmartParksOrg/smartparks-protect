import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CurrentState, Feature, Page as PageType, Track } from "@/api/types";
import { Icon } from "@/components/icons/Icon";
import { type BasemapKey, BASEMAPS, loadBasemap, saveBasemap } from "@/components/map/basemap";
import { type EntityFeatureProperties, ensureEntityLayers, ensureEventLayers, ensureFeatureLayers, ensureTrackLayers, setEntities, setEvents, setFeatures, setTrack, SOURCES } from "@/components/map/layers";
import { useMap } from "@/components/map/useMap";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useProjectStream } from "@/hooks/useProjectStream";
import { formatAgo, formatTime } from "@/lib/format";
import { EventDetailDialog } from "@/pages/project/EventsPage";
import { useProjectStore } from "@/stores/project";

interface CurrentFeature {
  type: "Feature";
  id: string;
  geometry: GeoJSON.Point;
  properties: EntityFeatureProperties;
}

const TRACK_PERIODS = [{ label: "6 hours", hours: 6 }, { label: "24 hours", hours: 24 }, { label: "7 days", hours: 168 }, { label: "30 days", hours: 720 }];

/**
 * Live map (architecture 11 and 13). Entities come from the current-state endpoint (bounded),
 * updates arrive over the WebSocket, a selected entity shows its panel and optional track. The
 * container has `z-0` so MapLibre's internals never paint over the app (z-index ladder).
 */
export function MapPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("entity");
  const trackHours = Number(params.get("track") ?? 0);
  const [basemap, setBasemap] = useState<BasemapKey>(loadBasemap);
  const container = useRef<HTMLDivElement | null>(null);
  const { mapRef, ready } = useMap(container, basemap, [31.5, -24.9], 6);
  const client = useQueryClient();
  const navigate = useNavigate();
  const selectedEvent = params.get("event");
  const setLast = useProjectStore((s) => s.setLastProjectId);
  useEffect(() => setLast(projectId), [projectId, setLast]);

  const current = useQuery({ queryKey: queryKeys.currentState(projectId), queryFn: () => api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`), refetchInterval: 60_000 });
  const currentFeatures = current.data?.features as unknown as CurrentFeature[] | undefined;
  const features = useQuery({ queryKey: queryKeys.features(projectId), queryFn: () => api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, { query: { limit: 500 } }) });
  const events = useQuery({ queryKey: queryKeys.mapEvents(projectId, 24), queryFn: () => api.get<GeoJSON.FeatureCollection>(`/api/v1/projects/${projectId}/map/events`, { query: { hours: 24, limit: 500 } }), refetchInterval: 120_000 });
  const trackQuery = useMemo(() => ({ entity_id: selectedId, hours: trackHours, max_points: 5000 }), [selectedId, trackHours]);
  const track = useQuery({
    queryKey: queryKeys.track(projectId, trackQuery),
    queryFn: () => api.get<Track>(`/api/v1/projects/${projectId}/tracks`, { query: { entity_id: selectedId, max_points: 5000, from: new Date(Date.now() - trackHours * 3600_000).toISOString() } }),
    enabled: Boolean(selectedId && trackHours > 0),
  });

  const select = useCallback(
    (id: string | null) =>
      setParams(
        (p) => {
          if (id) p.set("entity", id);
          else {
            p.delete("entity");
            p.delete("track");
          }
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );

  // live updates: patch the cached current state and refetch tracks
  useProjectStream(projectId, (message) => {
    if (message.topic === "position.created") {
      client.setQueryData<CurrentState>(queryKeys.currentState(projectId), (old) => {
        if (!old) return old;
        const entityId = message.entity_id as string | null;
        if (!entityId) return old;
        const time = message.time as string;
        const features = (old.features as unknown as CurrentFeature[]).map((f) => (f.properties.entity_id === entityId ? { ...f, geometry: { type: "Point" as const, coordinates: [message.longitude as number, message.latitude as number] }, properties: { ...f.properties, last_seen_at: time, position_time: time, device_id: message.device_id as string | null } } : f));
        return { ...old, features: features as unknown as CurrentState["features"] };
      });
      if (message.entity_id === selectedId) void client.invalidateQueries({ queryKey: queryKeys.track(projectId, trackQuery) });
    }
    if (message.topic === "event.created" || message.topic === "alert.created") {
      void client.invalidateQueries({ queryKey: queryKeys.mapEvents(projectId, 24) });
      void client.invalidateQueries({ queryKey: queryKeys.currentState(projectId) });
    }
  });

  // layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureEntityLayers(map, (props) => select(props.entity_id), (lngLat, clusterId) => {
      const source = map.getSource(SOURCES.entities) as maplibregl.GeoJSONSource;
      void source.getClusterExpansionZoom(clusterId).then((zoom) => map.easeTo({ center: lngLat, zoom }));
    });
    ensureFeatureLayers(map);
    ensureTrackLayers(map);
    ensureEventLayers(map, (props) => setParams((p) => { p.set("event", props.event_id); return p; }, { replace: true }));
  }, [mapRef, ready, select, setParams]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !events.data) return;
    void setEvents(map, events.data.features);
  }, [mapRef, ready, events.data]);

  const fitted = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !currentFeatures) return;
    void setEntities(map, currentFeatures as unknown as GeoJSON.Feature[], selectedId);
    if (!fitted.current && currentFeatures.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const f of currentFeatures) bounds.extend(f.geometry.coordinates as [number, number]);
      map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 0 });
      fitted.current = true;
    }
  }, [mapRef, ready, currentFeatures, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !features.data) return;
    setFeatures(map, features.data.items.filter((f) => f.geometry).map((f) => ({ type: "Feature", geometry: f.geometry as unknown as GeoJSON.Geometry, properties: { name: f.name, feature_type: f.feature_type } })));
  }, [mapRef, ready, features.data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (track.data && selectedId && trackHours > 0) setTrack(map, track.data.geometry as unknown as GeoJSON.Geometry, track.data.times);
    else setTrack(map, null, []);
  }, [mapRef, ready, track.data, selectedId, trackHours]);

  const selected = currentFeatures?.find((f) => f.properties.entity_id === selectedId)?.properties;

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={container} className="absolute! inset-0 z-0" />
      <div className="absolute left-3 top-3 z-10 flex items-center gap-2">
        <Select value={basemap} onValueChange={(v) => { setBasemap(v as BasemapKey); saveBasemap(v as BasemapKey); }}>
          <SelectTrigger className="h-9 w-32 bg-card"><Layers className="size-4" /><SelectValue /></SelectTrigger>
          <SelectContent>{Object.entries(BASEMAPS).map(([key, b]) => <SelectItem key={key} value={key}>{b.label}</SelectItem>)}</SelectContent>
        </Select>
        {current.data && <Badge variant="secondary" className="bg-card">{current.data.total} entities{current.data.use_tiles ? ", tiles" : ""}</Badge>}
        {events.data && events.data.features.length > 0 && <Badge variant="secondary" className="bg-card cursor-pointer" onClick={() => void navigate(`/projects/${projectId}/rules/events`)}>{events.data.features.length} events, 24 h</Badge>}
      </div>
      {selected && (
        <aside className="absolute bottom-3 left-3 right-3 z-10 max-h-[45%] overflow-y-auto rounded-lg border bg-card p-4 shadow-lg md:right-auto md:w-80">
          <div className="flex items-start gap-2">
            <Icon iconKey={selected.icon_key} className="size-7 text-primary" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{selected.name}</div>
              <div className="text-xs text-muted-foreground">{selected.entity_type}</div>
            </div>
            <Button variant="ghost" size="icon" aria-label="Close" onClick={() => select(null)}><X className="size-4" /></Button>
          </div>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Last seen</dt><dd title={formatTime(selected.last_seen_at)}>{formatAgo(selected.last_seen_at)}</dd>
            <dt className="text-muted-foreground">Position</dt><dd>{formatTime(selected.position_time)}</dd>
            <dt className="text-muted-foreground">Device</dt><dd>{selected.device_id ? <Link className="underline" to={`/projects/${projectId}/devices/${selected.device_id}`}>open device</Link> : "none"}</dd>
            <dt className="text-muted-foreground">Alerts</dt><dd>{selected.active_alert_count > 0 ? <Link className="underline" to={`/projects/${projectId}/alerts`}>{selected.active_alert_count} open</Link> : "none"}</dd>
          </dl>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Select value={String(trackHours)} onValueChange={(v) => setParams((p) => { if (v === "0") p.delete("track"); else p.set("track", v); return p; }, { replace: true })}>
              <SelectTrigger className="h-8 w-36"><SelectValue placeholder="Track" /></SelectTrigger>
              <SelectContent><SelectItem value="0">No track</SelectItem>{TRACK_PERIODS.map((p) => <SelectItem key={p.hours} value={String(p.hours)}>Track {p.label}</SelectItem>)}</SelectContent>
            </Select>
            {track.data && <span className="text-xs text-muted-foreground">{track.data.returned_points} of {track.data.total_points} points</span>}
          </div>
        </aside>
      )}
      <EventDetailDialog scope={projectId} eventId={selectedEvent} onClose={() => setParams((p) => { p.delete("event"); return p; }, { replace: true })} />
    </div>
  );
}
