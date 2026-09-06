import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, ListTree, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  CoverageResponse,
  CurrentState,
  Feature,
  Gateway,
  Page as PageType,
  Track,
} from "@/api/types";
import { Icon } from "@/components/icons/Icon";
import {
  type BasemapKey,
  BASEMAPS,
  loadBasemap,
  saveBasemap,
} from "@/components/map/basemap";
import {
  type EntityFeatureProperties,
  ensureEntityLayers,
  ensureEventLayers,
  ensureFeatureLayers,
  ensureCoverageLayers,
  ensureGatewayLayers,
  ensureTrackLayers,
  type EventFeatureProperties,
  setCoverage,
  setEntities,
  setEvents,
  setFeatures,
  setGateways,
  setTrack,
  SOURCES,
} from "@/components/map/layers";
import {
  DEFAULT_LAYERS,
  isEventVisible,
  isFeatureVisible,
  isGatewayVisible,
  isVisible,
  type LayerChoices,
} from "@/components/map/layerChoices";
import { LayerPanel } from "@/components/map/LayerPanel";
import { useMap } from "@/components/map/useMap";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGroups } from "@/hooks/useGroups";
import { usePreference } from "@/hooks/usePreference";
import { useProjectStream } from "@/hooks/useProjectStream";
import { useNow } from "@/hooks/useNow";
import { formatAgo, formatTime } from "@/lib/format";
import { EventDetailDialog } from "@/pages/project/EventsPage";
import { useProjectStore } from "@/stores/project";

/** Fly to a feature: a point gets a close zoom, everything else fits its bounds. */
function fitGeometry(
  map: maplibregl.Map | null,
  geometry: GeoJSON.Geometry,
): void {
  if (!map) return;
  if (geometry.type === "Point") {
    map.easeTo({
      center: geometry.coordinates as [number, number],
      zoom: Math.max(map.getZoom(), 13),
    });
    return;
  }
  const bounds = new maplibregl.LngLatBounds();
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number")
      bounds.extend(c as [number, number]);
    else if (Array.isArray(c)) c.forEach(walk);
  };
  if ("coordinates" in geometry) walk(geometry.coordinates);
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 80, maxZoom: 15 });
}

interface CurrentFeature {
  type: "Feature";
  id: string;
  geometry: GeoJSON.Point;
  properties: EntityFeatureProperties;
}

const TRACK_PERIODS = [
  { label: i18n.t("6 hours"), hours: 6 },
  { label: i18n.t("24 hours"), hours: 24 },
  { label: i18n.t("7 days"), hours: 168 },
  { label: i18n.t("30 days"), hours: 720 },
];

/**
 * Live map (architecture 11 and 13). Entities come from the current-state endpoint (bounded),
 * updates arrive over the WebSocket, a selected entity shows its panel and optional track. The
 * container has `z-0` so MapLibre's internals never paint over the app (z-index ladder).
 */
export function MapPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const now = useNow();
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

  const current = useQuery({
    queryKey: queryKeys.currentState(projectId),
    queryFn: () =>
      api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`),
    refetchInterval: 60_000,
  });
  const currentFeatures = current.data?.features as unknown as
    CurrentFeature[] | undefined;
  const groups = useGroups(projectId);
  const [allLayers, setAllLayers] = usePreference<
    Record<string, Partial<LayerChoices>>
  >("map_layers", {});
  const layers = useMemo<LayerChoices>(
    () => ({ ...DEFAULT_LAYERS, ...allLayers[projectId] }),
    [allLayers, projectId],
  );
  const setLayers = useCallback(
    (next: LayerChoices) => setAllLayers({ ...allLayers, [projectId]: next }),
    [allLayers, projectId, setAllLayers],
  );
  const [panelOpen, setPanelOpen] = useState(false);
  const visibleFeatures = useMemo(
    () =>
      currentFeatures?.filter((f) =>
        isVisible(f.properties, layers, groups.data),
      ),
    [currentFeatures, layers, groups.data],
  );
  const features = useQuery({
    queryKey: queryKeys.features(projectId),
    queryFn: () =>
      api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, {
        query: { limit: 500 },
      }),
  });
  const [viewport, setViewport] = useState<{
    bbox: string;
    zoom: number;
  } | null>(null);
  const gateways = useQuery({
    queryKey: queryKeys.gateways(projectId, 168),
    queryFn: () =>
      api.get<Gateway[]>(`/api/v1/projects/${projectId}/gateways`, {
        query: { hours: 168, limit: 500 },
      }),
    refetchInterval: 120_000,
  });
  const coverageGateways = useMemo(
    () =>
      layers.hidden_gateways.length > 0 && gateways.data
        ? gateways.data
            .filter((g) => !layers.hidden_gateways.includes(g.id))
            .map((g) => g.id)
        : undefined,
    [layers.hidden_gateways, gateways.data],
  );
  const coverageParams = useMemo(
    () => ({
      bbox: viewport?.bbox,
      zoom: viewport?.zoom ?? 8,
      hours: layers.coverage_hours,
      gateway_id: coverageGateways,
    }),
    [viewport, layers.coverage_hours, coverageGateways],
  );
  const coverage = useQuery({
    queryKey: queryKeys.coverage(projectId, coverageParams),
    queryFn: () =>
      api.get<CoverageResponse>(`/api/v1/projects/${projectId}/coverage`, {
        query: coverageParams,
      }),
    enabled: layers.coverage && viewport !== null,
    placeholderData: (previous) => previous,
    refetchInterval: 120_000,
  });
  const events = useQuery({
    queryKey: queryKeys.mapEvents(projectId, 24),
    queryFn: () =>
      api.get<GeoJSON.FeatureCollection>(
        `/api/v1/projects/${projectId}/map/events`,
        { query: { hours: 24, limit: 500 } },
      ),
    refetchInterval: 120_000,
  });
  const trackQuery = useMemo(
    () => ({ entity_id: selectedId, hours: trackHours, max_points: 5000 }),
    [selectedId, trackHours],
  );
  const track = useQuery({
    queryKey: queryKeys.track(projectId, trackQuery),
    queryFn: () =>
      api.get<Track>(`/api/v1/projects/${projectId}/tracks`, {
        query: {
          entity_id: selectedId,
          max_points: 5000,
          from: new Date(Date.now() - trackHours * 3600_000).toISOString(),
        },
      }),
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
      client.setQueryData<CurrentState>(
        queryKeys.currentState(projectId),
        (old) => {
          if (!old) return old;
          const entityId = message.entity_id as string | null;
          if (!entityId) return old;
          const time = message.time as string;
          const features = (old.features as unknown as CurrentFeature[]).map(
            (f) =>
              f.properties.entity_id === entityId
                ? {
                    ...f,
                    geometry: {
                      type: "Point" as const,
                      coordinates: [
                        message.longitude as number,
                        message.latitude as number,
                      ],
                    },
                    properties: {
                      ...f.properties,
                      last_seen_at: time,
                      position_time: time,
                      device_id: message.device_id as string | null,
                    },
                  }
                : f,
          );
          return {
            ...old,
            features: features as unknown as CurrentState["features"],
          };
        },
      );
      if (message.entity_id === selectedId)
        void client.invalidateQueries({
          queryKey: queryKeys.track(projectId, trackQuery),
        });
    }
    if (
      message.topic === "event.created" ||
      message.topic === "alert.created"
    ) {
      void client.invalidateQueries({
        queryKey: queryKeys.mapEvents(projectId, 24),
      });
      void client.invalidateQueries({
        queryKey: queryKeys.currentState(projectId),
      });
    }
  });

  // layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureEntityLayers(
      map,
      (props) => select(props.entity_id),
      (lngLat, clusterId) => {
        const source = map.getSource(
          SOURCES.entities,
        ) as maplibregl.GeoJSONSource;
        void source
          .getClusterExpansionZoom(clusterId)
          .then((zoom) => map.easeTo({ center: lngLat, zoom }));
      },
    );
    ensureFeatureLayers(map);
    ensureGatewayLayers(map);
    ensureCoverageLayers(map);
    ensureTrackLayers(map);
    ensureEventLayers(map, (props) =>
      setParams(
        (p) => {
          p.set("event", props.event_id);
          return p;
        },
        { replace: true },
      ),
    );
  }, [mapRef, ready, select, setParams]);

  // the viewport for the coverage query, settled a moment after the map stops moving
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const update = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        const b = map.getBounds();
        setViewport({
          bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
            .map((v) => v.toFixed(5))
            .join(","),
          zoom: Math.round(map.getZoom()),
        });
      }, 400);
    };
    update();
    map.on("moveend", update);
    return () => {
      map.off("moveend", update);
      if (timer) clearTimeout(timer);
    };
  }, [mapRef, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setCoverage(
      map,
      layers.coverage && coverage.data
        ? (coverage.data.features as unknown as GeoJSON.Feature[])
        : [],
    );
  }, [mapRef, ready, layers.coverage, coverage.data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !gateways.data) return;
    setGateways(
      map,
      gateways.data
        .filter((g) => g.geometry && isGatewayVisible(g.id, layers))
        .map((g) => ({
          type: "Feature",
          geometry: g.geometry as unknown as GeoJSON.Geometry,
          properties: {
            gateway_id: g.id,
            name: g.display_name,
            last_seen_at: g.last_seen_at,
          },
        })),
    );
  }, [mapRef, ready, gateways.data, layers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !events.data) return;
    void setEvents(
      map,
      events.data.features.filter((f) =>
        isEventVisible(
          f.properties as unknown as EventFeatureProperties,
          layers,
        ),
      ),
    );
  }, [mapRef, ready, events.data, layers]);

  const featureParam = params.get("feature");
  const fittedFeature = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (
      !map ||
      !ready ||
      !featureParam ||
      !features.data ||
      fittedFeature.current === featureParam
    )
      return;
    const f = features.data.items.find((x) => x.id === featureParam);
    if (f?.geometry) {
      fitGeometry(map, f.geometry as unknown as GeoJSON.Geometry);
      fittedFeature.current = featureParam;
    }
  }, [mapRef, ready, featureParam, features.data]);

  const fitted = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !currentFeatures || !visibleFeatures) return;
    void setEntities(
      map,
      visibleFeatures as unknown as GeoJSON.Feature[],
      selectedId,
    );
    if (!fitted.current && currentFeatures.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const f of currentFeatures)
        bounds.extend(f.geometry.coordinates as [number, number]);
      map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 0 });
      fitted.current = true;
    }
  }, [mapRef, ready, currentFeatures, visibleFeatures, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !features.data) return;
    setFeatures(
      map,
      features.data.items
        .filter((f) => f.geometry && isFeatureVisible(f, layers))
        .map((f) => ({
          type: "Feature",
          geometry: f.geometry as unknown as GeoJSON.Geometry,
          properties: { id: f.id, name: f.name, feature_type: f.feature_type },
        })),
    );
  }, [mapRef, ready, features.data, layers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (track.data && selectedId && trackHours > 0)
      setTrack(
        map,
        track.data.geometry as unknown as GeoJSON.Geometry,
        track.data.times,
      );
    else setTrack(map, null, []);
  }, [mapRef, ready, track.data, selectedId, trackHours]);

  const selected = currentFeatures?.find(
    (f) => f.properties.entity_id === selectedId,
  )?.properties;

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={container} className="absolute! inset-0 z-0" />
      <div
        className={`absolute top-3 z-10 flex items-center gap-2 ${panelOpen ? "left-[23rem]" : "left-3"}`}
      >
        <Select
          value={basemap}
          onValueChange={(v) => {
            setBasemap(v as BasemapKey);
            saveBasemap(v as BasemapKey);
          }}
        >
          <SelectTrigger className="h-9 w-32 bg-card">
            <Layers className="size-4" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(BASEMAPS).map(([key, b]) => (
              <SelectItem key={key} value={key}>
                {b.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant={panelOpen ? "default" : "outline"}
          size="sm"
          className={panelOpen ? "" : "bg-card"}
          aria-pressed={panelOpen}
          onClick={() => setPanelOpen((o) => !o)}
        >
          <ListTree className="size-4" /> {t("Layers")}
        </Button>
        {current.data && (
          <Badge variant="secondary" className="bg-card">
            {visibleFeatures &&
            visibleFeatures.length !== currentFeatures?.length
              ? `${visibleFeatures.length} / `
              : ""}
            {current.data.total} {t("entities")}
            {current.data.use_tiles ? ", tiles" : ""}
          </Badge>
        )}
        {events.data && events.data.features.length > 0 && (
          <Badge
            variant="secondary"
            className="bg-card cursor-pointer"
            onClick={() => void navigate(`/projects/${projectId}/rules/events`)}
          >
            {events.data.features.length} {t("events, 24 h")}
          </Badge>
        )}
      </div>
      {panelOpen && currentFeatures && (
        <LayerPanel
          entities={currentFeatures.map((f) => f.properties)}
          groups={groups.data}
          features={features.data?.items ?? []}
          events={(events.data?.features ?? []).map(
            (f) => f.properties as unknown as EventFeatureProperties,
          )}
          gateways={gateways.data ?? []}
          coverage={layers.coverage ? coverage.data : undefined}
          choices={layers}
          trackedId={selectedId && trackHours > 0 ? selectedId : null}
          onChange={setLayers}
          onClose={() => setPanelOpen(false)}
          onToggleTrack={(id) =>
            setParams(
              (p) => {
                if (p.get("entity") === id && Number(p.get("track") ?? 0) > 0)
                  p.delete("track");
                else {
                  p.set("entity", id);
                  p.set("track", "24");
                }
                return p;
              },
              { replace: true },
            )
          }
          onPickGateway={(id) => {
            const g = gateways.data?.find((x) => x.id === id);
            if (g?.geometry)
              fitGeometry(
                mapRef.current,
                g.geometry as unknown as GeoJSON.Geometry,
              );
          }}
          onPickEntity={(id) => {
            select(id);
            const f = currentFeatures.find(
              (x) => x.properties.entity_id === id,
            );
            if (f)
              mapRef.current?.easeTo({
                center: f.geometry.coordinates as [number, number],
                zoom: Math.max(mapRef.current.getZoom(), 12),
              });
          }}
          onPickFeature={(id) => {
            const f = features.data?.items.find((x) => x.id === id);
            if (f?.geometry)
              fitGeometry(
                mapRef.current,
                f.geometry as unknown as GeoJSON.Geometry,
              );
          }}
          onPickEvent={(id) => {
            const f = events.data?.features.find(
              (x) =>
                (x.properties as unknown as EventFeatureProperties).event_id ===
                id,
            );
            if (f?.geometry.type === "Point")
              mapRef.current?.easeTo({
                center: f.geometry.coordinates as [number, number],
                zoom: Math.max(mapRef.current.getZoom(), 12),
              });
          }}
        />
      )}
      {selected && (
        <aside className="absolute bottom-3 left-3 right-3 z-10 max-h-[45%] overflow-y-auto rounded-lg border bg-card p-4 shadow-lg md:right-auto md:w-80">
          <div className="flex items-start gap-2">
            <Icon iconKey={selected.icon_key} className="size-7 text-primary" />
            <div className="min-w-0 flex-1">
              <Link
                className="block truncate font-semibold underline-offset-2 hover:underline"
                to={`/projects/${projectId}/entities/${selected.entity_id}`}
              >
                {selected.name}
              </Link>
              <div className="text-xs text-muted-foreground">
                {selected.entity_type}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("Close")}
              onClick={() => select(null)}
            >
              <X className="size-4" />
            </Button>
          </div>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">{t("Last seen")}</dt>
            <dd title={formatTime(selected.last_seen_at)}>
              {formatAgo(selected.last_seen_at, now)}
            </dd>
            <dt className="text-muted-foreground">{t("Position")}</dt>
            <dd>{formatTime(selected.position_time)}</dd>
            {selected.battery_voltage != null && (
              <>
                <dt className="text-muted-foreground">{t("Battery")}</dt>
                <dd
                  className={
                    selected.health_level === "critical"
                      ? "text-destructive"
                      : selected.health_level === "warn"
                        ? "text-brand-sand"
                        : ""
                  }
                >
                  {selected.battery_voltage.toFixed(2)} V
                </dd>
              </>
            )}
            {selected.last_status_at && (
              <>
                <dt className="text-muted-foreground">{t("Last status")}</dt>
                <dd title={formatTime(selected.last_status_at)}>
                  {formatAgo(selected.last_status_at, now)}
                </dd>
              </>
            )}
            <dt className="text-muted-foreground">{t("Device")}</dt>
            <dd>
              {selected.device_id ? (
                <Link
                  className="underline"
                  to={`/projects/${projectId}/devices/${selected.device_id}`}
                >
                  {t("open device")}
                </Link>
              ) : (
                "none"
              )}
            </dd>
            <dt className="text-muted-foreground">{t("Alerts")}</dt>
            <dd>
              {selected.active_alert_count > 0 ? (
                <Link
                  className="underline"
                  to={`/projects/${projectId}/alerts`}
                >
                  {selected.active_alert_count} {t("open")}
                </Link>
              ) : (
                "none"
              )}
            </dd>
          </dl>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Select
              value={String(trackHours)}
              onValueChange={(v) =>
                setParams(
                  (p) => {
                    if (v === "0") p.delete("track");
                    else p.set("track", v);
                    return p;
                  },
                  { replace: true },
                )
              }
            >
              <SelectTrigger className="h-8 w-36">
                <SelectValue placeholder={t("Track")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="0">{t("No track")}</SelectItem>
                {TRACK_PERIODS.map((p) => (
                  <SelectItem key={p.hours} value={String(p.hours)}>
                    {t("Track")} {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {track.data && (
              <span className="text-xs text-muted-foreground">
                {t("{{returned}} of {{total}} points", {
                  returned: track.data.returned_points,
                  total: track.data.total_points,
                })}
              </span>
            )}
          </div>
        </aside>
      )}
      <EventDetailDialog
        scope={projectId}
        eventId={selectedEvent}
        onClose={() =>
          setParams(
            (p) => {
              p.delete("event");
              return p;
            },
            { replace: true },
          )
        }
      />
    </div>
  );
}
