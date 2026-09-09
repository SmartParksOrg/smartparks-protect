import { useTranslation } from "react-i18next";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Flame,
  Layers,
  ListTree,
  Mountain,
  PenLine,
  Route,
  Ruler,
} from "lucide-react";
import * as maplibregl from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  CoverageResponse,
  CurrentState,
  Feature,
  Gateway,
  HeatResponse,
  Page as PageType,
  Track,
} from "@/api/types";
import {
  SourceEventDialog,
  TraceDialog,
} from "@/components/devices/ProvenancePanel";
import {
  type BasemapKey,
  basemapsFor,
  basemapStyle,
  loadBasemap,
  saveBasemap,
} from "@/components/map/basemap";
import {
  setTerrain,
  TERRAIN_PITCH,
  terrainTileJson,
} from "@/components/map/terrain";
import {
  bindDeviceClicks,
  bindEntityClicks,
  bindEventClicks,
  bindFeatureClicks,
  bindGatewayClicks,
  bindTrackPointClicks,
  type DeviceFeatureProperties,
  type EntityFeatureProperties,
  ensureDeviceLayers,
  ensureEntityLayers,
  ensureEventLayers,
  ensureFeatureLayers,
  ensureCoverageLayers,
  ensureGatewayLayers,
  ensureHeatLayer,
  ensureTrackLayers,
  type EventFeatureProperties,
  setCoverage,
  setDevices,
  setEntities,
  setEvents,
  setFeatures,
  setGateways,
  setHeatPaint,
  setHeatPoints,
  setSelectedTrackPoint,
  setTracks,
  SOURCES,
  trackPointKey,
} from "@/components/map/layers";
import {
  DEFAULT_LAYERS,
  isEventVisible,
  isFeatureVisible,
  isDeviceShown,
  isGatewayVisible,
  isVisible,
  type LayerChoices,
  coverageGatewayIds,
  revealDevice,
  revealEntity,
  revealFeature,
  revealGateway,
} from "@/components/map/layerChoices";
import { ControlStrip, type StripItem } from "@/components/map/ControlStrip";
import {
  createDrawSession,
  type DrawKind,
  type DrawSession,
} from "@/components/map/draw";
import {
  DrawBar,
  SaveFeatureDialog,
  type SaveFeatureValues,
} from "@/components/map/DrawBar";
import { FeaturePanel } from "@/components/map/FeaturePanel";
import { boundsOf } from "@/components/map/fit";
import {
  DEFAULT_HEAT,
  type HeatSettings,
  parseHeatSettings,
} from "@/components/map/heat";
import { HeatCard, HeatSettingsPanel } from "@/components/map/HeatSettings";
import { GatewayPanel } from "@/components/map/GatewayPanel";
import { LayerPanel } from "@/components/map/LayerPanel";
import { DevicePanel, EntityPanel } from "@/components/map/MapObjectPanel";
import { PointPanel } from "@/components/map/PointPanel";
import {
  DEFAULT_TRACK_HOURS,
  parseTrackLength,
  trackFrom,
  type TrackLength,
  trackLengthParam,
} from "@/components/map/trackLength";
import { TracksCard, TrackSettingsPanel } from "@/components/map/TrackSettings";
import { useTrackLengthLabel } from "@/components/map/useTrackLengthLabel";
import { useMap } from "@/components/map/useMap";
import { Badge } from "@/components/ui/badge";
import { useGroups } from "@/hooks/useGroups";
import { usePreference } from "@/hooks/usePreference";
import { useProjectStream } from "@/hooks/useProjectStream";
import { useNow } from "@/hooks/useNow";
import { useIsPhone } from "@/hooks/useMediaQuery";
import { useMapConfig } from "@/hooks/useMapConfig";
import { EventDetailDialog } from "@/pages/project/EventsPage";
import { isAllProjects } from "@/lib/scope";
import { canAdmin, useProjectRole, useProjects } from "@/hooks/useProjects";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useAuthStore } from "@/stores/auth";
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

interface DeviceFeature {
  type: "Feature";
  id: string;
  geometry: GeoJSON.Point | null;
  properties: DeviceFeatureProperties;
}

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
  const selectedDeviceId = params.get("device");
  // a gateway or a track point selected (phase 19): `?gateway=<id>`, `?point=<owner>,<time>`
  const selectedGatewayId = params.get("gateway");
  const selectedPoint = useMemo(() => {
    const raw = params.get("point");
    if (!raw) return null;
    const comma = raw.indexOf(",");
    if (comma < 0) return null;
    return { ownerId: raw.slice(0, comma), time: raw.slice(comma + 1) };
  }, [params]);
  const [sourceEvent, setSourceEvent] = useState<{
    id: number;
    ingestedAt: string;
  } | null>(null);
  const [trace, setTrace] = useState<string | null>(null);
  // one track length for every track: the URL has it, the last choice is the default (D109)
  const [preferredLength, setPreferredLength] = usePreference<TrackLength>(
    "track_length",
    DEFAULT_TRACK_HOURS,
  );
  const trackLength = parseTrackLength(params.get("track"), preferredLength);
  const fallbackHours =
    typeof preferredLength === "number" ? preferredLength : DEFAULT_TRACK_HOURS;
  const trackLengthLabel = useTrackLengthLabel(trackLength);
  const [trackSettingsOpen, setTrackSettingsOpen] = useState(false);
  const trackedIds = useMemo(
    () => (params.get("tracks") ?? "").split(",").filter(Boolean),
    [params],
  );
  const trackedDeviceIds = useMemo(
    () => (params.get("device_tracks") ?? "").split(",").filter(Boolean),
    [params],
  );
  const [basemap, setBasemap] = useState<BasemapKey>(loadBasemap);
  // satellite imagery and terrain need the server's MapTiler key (decision D141)
  const { maptilerKey } = useMapConfig();
  const basemaps = useMemo(() => basemapsFor(maptilerKey), [maptilerKey]);
  const [terrainOn, setTerrainOn] = usePreference<boolean>("terrain", false);
  const container = useRef<HTMLDivElement | null>(null);
  const { mapRef, ready, stripHost } = useMap(
    container,
    basemapStyle(basemap, basemaps),
    [31.5, -24.9],
    6,
  );
  const client = useQueryClient();
  const navigate = useNavigate();
  const selectedEvent = params.get("event");
  const setLast = useProjectStore((s) => s.setLastProjectId);
  useEffect(() => setLast(projectId), [projectId, setLast]);
  // the all scope (decision D117): the project is the top level of the layers panel and the
  // panels name it; links go to the object's own project
  const allProjects = isAllProjects(projectId);
  const projectList = useProjects();
  const user = useAuthStore((s) => s.user);
  const projectName = (id: string | null | undefined) =>
    projectList.data?.items.find((p) => p.id === id)?.name ?? "";

  const current = useQuery({
    queryKey: queryKeys.currentState(projectId),
    queryFn: () =>
      api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`),
    refetchInterval: 60_000,
  });
  const currentFeatures = current.data?.features as unknown as
    CurrentFeature[] | undefined;
  // the device layer (decision D111): every device of the project, drawn when switched on
  const devices = useQuery({
    queryKey: queryKeys.mapDevices(projectId),
    queryFn: () =>
      api.get<CurrentState>(`/api/v1/projects/${projectId}/map/devices`),
    refetchInterval: 60_000,
  });
  const deviceFeatures = devices.data?.features as unknown as
    DeviceFeature[] | undefined;
  const groups = useGroups(projectId);
  const [allLayers, setAllLayers] = usePreference<
    Record<string, Partial<LayerChoices>>
  >("map_layers", {});
  // gateways are the network, not the animals: off by default for everyone, switched on in
  // the layers panel and remembered per user (decision D134); a `?gateways=1` or `?gateway=`
  // link switches the layer on and keeps it (phase 19, the reveal effect below)
  const gatewayParam = selectedGatewayId;
  const layers = useMemo<LayerChoices>(
    () => ({
      ...DEFAULT_LAYERS,
      gateways: false,
      ...allLayers[projectId],
    }),
    [allLayers, projectId],
  );
  const setLayers = useCallback(
    (next: LayerChoices) => setAllLayers({ ...allLayers, [projectId]: next }),
    [allLayers, projectId, setAllLayers],
  );
  // the layers panel's state lives in the URL (`?layers=1`) so a link and the sweep reach it
  const panelOpen = params.get("layers") === "1";
  const setPanelOpen = useCallback(
    (open: boolean) =>
      setParams(
        (p) => {
          if (open) p.set("layers", "1");
          else p.delete("layers");
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );
  // the Tracks card shows while tracks are on unless folded from the strip
  const [tracksCardHidden, setTracksCardHidden] = useState(false);
  // heatmaps (decision D138): switched on per entity and device like the tracks (`?heat=` and
  // `?device_heat=` list them); the settings travel in the URL and the last ones are the
  // per-user default, one setting for every heatmap on the map
  const heatIds = useMemo(
    () => (params.get("heat") ?? "").split(",").filter(Boolean),
    [params],
  );
  const heatDeviceIds = useMemo(
    () => (params.get("device_heat") ?? "").split(",").filter(Boolean),
    [params],
  );
  const heatOn = heatIds.length + heatDeviceIds.length > 0;
  const [preferredHeat, setPreferredHeat] = usePreference<HeatSettings>(
    "heat_settings",
    DEFAULT_HEAT,
  );
  const heat = useMemo(
    () => parseHeatSettings(params, preferredHeat),
    [params, preferredHeat],
  );
  const [heatSettingsOpen, setHeatSettingsOpen] = useState(false);
  const [heatCardHidden, setHeatCardHidden] = useState(false);
  const setHeatLists = useCallback(
    (entityIds: string[], deviceIds: string[]) =>
      setParams(
        (p) => {
          if (entityIds.length > 0) p.set("heat", entityIds.join(","));
          else p.delete("heat");
          if (deviceIds.length > 0) p.set("device_heat", deviceIds.join(","));
          else p.delete("device_heat");
          if (entityIds.length + deviceIds.length === 0)
            for (const k of ["heat_radius", "heat_sensitivity", "heat_hours"])
              p.delete(k);
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );
  // plain functions: they close over the lists, which change with the URL
  const toggleHeat = (entityId: string) => {
    setHeatLists(
      heatIds.includes(entityId)
        ? heatIds.filter((x) => x !== entityId)
        : [...heatIds, entityId],
      heatDeviceIds,
    );
    setHeatCardHidden(false);
  };
  const toggleDeviceHeat = (deviceId: string) => {
    setHeatLists(
      heatIds,
      heatDeviceIds.includes(deviceId)
        ? heatDeviceIds.filter((x) => x !== deviceId)
        : [...heatDeviceIds, deviceId],
    );
    setHeatCardHidden(false);
  };
  const setHeat = useCallback(
    (next: HeatSettings) => {
      setPreferredHeat(next);
      setParams(
        (p) => {
          p.set("heat_radius", String(next.radius_m));
          p.set("heat_sensitivity", String(next.sensitivity));
          p.set("heat_hours", String(next.hours));
          return p;
        },
        { replace: true },
      );
    },
    [setParams, setPreferredHeat],
  );
  const visibleFeatures = useMemo(
    () =>
      currentFeatures?.filter((f) =>
        isVisible(f.properties, layers, groups.data, allProjects),
      ),
    [currentFeatures, layers, groups.data, allProjects],
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
      coverageGatewayIds(
        layers,
        (gateways.data ?? []).map((g) => g.id),
      ),
    [layers, gateways.data],
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
    queryFn: ({ signal }) =>
      api.get<CoverageResponse>(`/api/v1/projects/${projectId}/coverage`, {
        query: coverageParams,
        signal,
      }),
    enabled: layers.coverage && viewport !== null,
    retry: false,
    placeholderData: (previous) => previous,
    refetchInterval: 120_000,
  });
  const heatParams = useMemo(
    () => ({
      bbox: viewport?.bbox,
      hours: heat.hours,
      entity_id: heatIds,
      device_id: heatDeviceIds,
    }),
    [viewport, heat.hours, heatIds, heatDeviceIds],
  );
  const heatPoints = useQuery({
    queryKey: queryKeys.heat(projectId, heatParams),
    queryFn: ({ signal }) =>
      api.get<HeatResponse>(`/api/v1/projects/${projectId}/map/heat`, {
        query: heatParams,
        signal,
      }),
    enabled: heatOn && viewport !== null,
    retry: false,
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
  const assignedSince = useCallback(
    (entityId: string) =>
      currentFeatures?.find((f) => f.properties.entity_id === entityId)
        ?.properties.assigned_since ?? null,
    [currentFeatures],
  );
  const tracks = useQueries({
    queries: trackedIds.map((entityId) => ({
      queryKey: queryKeys.track(projectId, {
        entity_id: entityId,
        length: trackLengthParam(trackLength),
        since: trackLength === "assigned" ? assignedSince(entityId) : null,
        max_points: 5000,
      }),
      queryFn: () =>
        api.get<Track>(`/api/v1/projects/${projectId}/tracks`, {
          query: {
            entity_id: entityId,
            max_points: 5000,
            from: trackFrom(
              trackLength,
              assignedSince(entityId),
              fallbackHours,
            ),
          },
        }),
    })),
  });
  const projectSince = useCallback(
    (deviceId: string) =>
      deviceFeatures?.find((f) => f.properties.device_id === deviceId)
        ?.properties.project_since ?? null,
    [deviceFeatures],
  );
  const deviceTracks = useQueries({
    queries: trackedDeviceIds.map((deviceId) => ({
      queryKey: queryKeys.track(projectId, {
        device_id: deviceId,
        length: trackLengthParam(trackLength),
        since: trackLength === "assigned" ? projectSince(deviceId) : null,
        max_points: 5000,
      }),
      queryFn: () =>
        api.get<Track>(`/api/v1/projects/${projectId}/tracks`, {
          query: {
            device_id: deviceId,
            max_points: 5000,
            from: trackFrom(trackLength, projectSince(deviceId), fallbackHours),
          },
        }),
    })),
  });
  const trackPoints =
    tracks.reduce((n, q) => n + (q.data?.returned_points ?? 0), 0) +
    deviceTracks.reduce((n, q) => n + (q.data?.returned_points ?? 0), 0);
  const selectedTrack = selectedId
    ? tracks[trackedIds.indexOf(selectedId)]?.data
    : undefined;
  const setTracked = useCallback(
    (ids: string[], length?: TrackLength) =>
      setParams(
        (p) => {
          if (ids.length > 0) p.set("tracks", ids.join(","));
          else p.delete("tracks");
          if (length) p.set("track", trackLengthParam(length));
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );
  const setTrackedDevices = useCallback(
    (ids: string[], length?: TrackLength) =>
      setParams(
        (p) => {
          if (ids.length > 0) p.set("device_tracks", ids.join(","));
          else p.delete("device_tracks");
          if (length) p.set("track", trackLengthParam(length));
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );
  const setTrackLength = useCallback(
    (next: TrackLength) => {
      setPreferredLength(next);
      setParams(
        (p) => {
          p.set("track", trackLengthParam(next));
          return p;
        },
        { replace: true },
      );
    },
    [setParams, setPreferredLength],
  );

  // one panel at a time: selecting one kind of object clears the others
  const SELECTION_PARAMS = [
    "entity",
    "device",
    "gateway",
    "point",
    "feature",
    "revealed",
  ] as const;
  const selectOnly = useCallback(
    (key: (typeof SELECTION_PARAMS)[number], value: string | null) =>
      setParams(
        (p) => {
          for (const k of SELECTION_PARAMS) p.delete(k);
          if (value) p.set(key, value);
          return p;
        },
        { replace: true },
      ),
    // the list is a constant
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setParams],
  );
  const select = useCallback(
    (id: string | null) => selectOnly("entity", id),
    [selectOnly],
  );
  const selectDevice = useCallback(
    (id: string | null) => selectOnly("device", id),
    [selectOnly],
  );
  const selectGateway = useCallback(
    (id: string | null) => selectOnly("gateway", id),
    [selectOnly],
  );
  const selectPoint = useCallback(
    (ownerId: string | null, time?: string) =>
      selectOnly("point", ownerId && time ? `${ownerId},${time}` : null),
    [selectOnly],
  );
  const selectFeature = useCallback(
    (id: string | null) => selectOnly("feature", id),
    [selectOnly],
  );

  // drawing and measuring (decisions D139 and D141): a tool is transient, not in the URL
  const role = useProjectRole(projectId);
  const canEdit = canAdmin(role) || Boolean(user?.is_superuser);
  const [tool, setTool] = useState<"draw" | "measure" | null>(null);
  const [drawKind, setDrawKind] = useState<DrawKind>("polygon");
  const [drawn, setDrawn] = useState<GeoJSON.Geometry | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const drawSession = useRef<DrawSession | null>(null);
  const endTool = useCallback(() => {
    setTool(null);
    setSaveOpen(false);
  }, []);
  const createFeature = useMutationToast({
    mutationFn: (values: SaveFeatureValues) =>
      api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
        body: { ...values, geometry: drawn },
      }),
    invalidate: [queryKeys.features(projectId)],
    success: t("Feature created"),
    onSuccess: (created) => {
      endTool();
      selectFeature(created.id);
    },
  });

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
      const deviceId = message.device_id as string | null;
      if (deviceId)
        client.setQueryData<CurrentState>(
          queryKeys.mapDevices(projectId),
          (old) => {
            if (!old) return old;
            const time = message.time as string;
            const features = (old.features as unknown as DeviceFeature[]).map(
              (f) =>
                f.properties.device_id === deviceId
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
      if (
        (typeof message.entity_id === "string" &&
          trackedIds.includes(message.entity_id)) ||
        (deviceId && trackedDeviceIds.includes(deviceId))
      )
        void client.invalidateQueries({
          queryKey: ["projects", projectId, "track"],
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

  // layers, once per map style
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureEntityLayers(map);
    ensureDeviceLayers(map);
    ensureFeatureLayers(map);
    ensureGatewayLayers(map);
    ensureCoverageLayers(map);
    ensureHeatLayer(map);
    ensureTrackLayers(map);
    ensureEventLayers(map);
  }, [mapRef, ready]);

  // terrain on top of any base map; a style change drops it, so it is applied again on ready
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setTerrain(
      map,
      terrainOn && maptilerKey ? terrainTileJson(maptilerKey) : null,
    );
  }, [mapRef, ready, terrainOn, maptilerKey]);
  const toggleTerrain = () => {
    const map = mapRef.current;
    const next = !terrainOn;
    setTerrainOn(next);
    map?.easeTo({ pitch: next ? TERRAIN_PITCH : 0, duration: 600 });
  };

  // the heatmap's points and paint
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setHeatPoints(
      map,
      heatOn && heatPoints.data
        ? (heatPoints.data.features as unknown as GeoJSON.Feature[])
        : [],
    );
  }, [mapRef, ready, heatOn, heatPoints.data]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setHeatPaint(map, heat.radius_m, map.getCenter().lat, heat.sensitivity);
  }, [mapRef, ready, heat.radius_m, heat.sensitivity, viewport]);

  // clicks, rebound whenever the URL writers change: `setParams` carries the current pathname,
  // and the map outlives a switch to another project on this page, so a handler bound once
  // would keep sending clicks to the first project's URL.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const unbindEntities = bindEntityClicks(
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
    const unbindDevices = bindDeviceClicks(
      map,
      (props) => selectDevice(props.device_id),
      (lngLat, clusterId) => {
        const source = map.getSource(
          SOURCES.devices,
        ) as maplibregl.GeoJSONSource;
        void source
          .getClusterExpansionZoom(clusterId)
          .then((zoom) => map.easeTo({ center: lngLat, zoom }));
      },
    );
    const unbindEvents = bindEventClicks(map, (props) =>
      setParams(
        (p) => {
          p.set("event", props.event_id);
          return p;
        },
        { replace: true },
      ),
    );
    const unbindGateways = bindGatewayClicks(map, (props) =>
      selectGateway(props.gateway_id),
    );
    const unbindPoints = bindTrackPointClicks(map, (props) =>
      selectPoint(props.owner_id, props.time),
    );
    const unbindFeatures = tool
      ? () => undefined
      : bindFeatureClicks(map, (props) => selectFeature(props.id));
    return () => {
      unbindEntities();
      unbindDevices();
      unbindEvents();
      unbindGateways();
      unbindPoints();
      unbindFeatures();
    };
  }, [
    mapRef,
    ready,
    select,
    selectDevice,
    selectGateway,
    selectPoint,
    selectFeature,
    setParams,
    tool,
  ]);

  // the draw session lives while a tool is on; a change of kind restarts the drawing
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !tool) return;
    const session = createDrawSession(map, setDrawn);
    drawSession.current = session;
    session.begin(drawKind);
    return () => {
      session.destroy();
      drawSession.current = null;
      setDrawn(null);
    };
    // the kind is applied through `begin` in changeDrawKind, not by recreating the session
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapRef, ready, tool]);
  const changeDrawKind = (kind: DrawKind) => {
    setDrawKind(kind);
    drawSession.current?.begin(kind);
  };

  // the clicked track point stays highlighted while its panel is open
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setSelectedTrackPoint(
      map,
      selectedPoint
        ? trackPointKey(selectedPoint.ownerId, selectedPoint.time)
        : null,
    );
  }, [mapRef, ready, selectedPoint]);

  const featureParamValue = params.get("feature");
  const featureParam = featureParamValue;

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
      }, 600);
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

  const fittedGateway = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (
      !map ||
      !ready ||
      !gatewayParam ||
      !gateways.data ||
      fittedGateway.current === gatewayParam
    )
      return;
    const g = gateways.data.find((x) => x.id === gatewayParam);
    if (g?.geometry) {
      fitGeometry(map, g.geometry as unknown as GeoJSON.Geometry);
      fittedGateway.current = gatewayParam;
    }
  }, [mapRef, ready, gatewayParam, gateways.data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !visibleFeatures) return;
    void setEntities(
      map,
      visibleFeatures as unknown as GeoJSON.Feature[],
      selectedId,
    );
  }, [mapRef, ready, visibleFeatures, selectedId]);

  // fit to the project once per visit, to its entities and devices together (phase 19): a park
  // whose collars have no animal yet, or hardware in the workshop, fits to the devices; without
  // any position the view stays where it was. Waits for both reads so the fit is not to half.
  const fittedProject = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || current.isPending || devices.isPending) return;
    if (fittedProject.current === projectId) return;
    fittedProject.current = projectId;
    // a link to a gateway or a feature fits to that object instead
    if (gatewayParam || featureParamValue) return;
    const bounds = boundsOf([
      ...(currentFeatures ?? []),
      ...(deviceFeatures ?? []),
    ]);
    if (bounds)
      map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 0 });
  }, [
    mapRef,
    ready,
    projectId,
    current.isPending,
    devices.isPending,
    currentFeatures,
    deviceFeatures,
    gatewayParam,
    featureParamValue,
  ]);

  // a "show on map" link lands on a visible object (phase 19): the object and its layer are
  // switched on once per arrival and the choice is kept, and the panel says it was hidden
  const revealed = useRef<string | null>(null);
  // `?revealed=<key>` says the panel's object was hidden until this visit; the URL carries it
  // so the note survives the re-render the layer change causes and clears with the selection
  const revealNote = params.get("revealed");
  useEffect(() => {
    const key = selectedId
      ? `entity:${selectedId}`
      : selectedDeviceId
        ? `device:${selectedDeviceId}`
        : selectedGatewayId
          ? `gateway:${selectedGatewayId}`
          : params.get("gateways") === "1"
            ? "gateways"
            : featureParamValue
              ? `feature:${featureParamValue}`
              : null;
    if (!key || revealed.current === key) return;
    let next: LayerChoices | null = null;
    if (selectedId) {
      const f = currentFeatures?.find(
        (x) => x.properties.entity_id === selectedId,
      );
      if (!currentFeatures) return; // not known yet
      if (f && !isVisible(f.properties, layers, groups.data, allProjects))
        next = revealEntity(layers, f.properties, groups.data, allProjects);
    } else if (selectedDeviceId) {
      if (!deviceFeatures) return;
      if (!isDeviceShown(selectedDeviceId, layers))
        next = revealDevice(layers, selectedDeviceId);
    } else if (selectedGatewayId) {
      if (!isGatewayVisible(selectedGatewayId, layers))
        next = revealGateway(layers, selectedGatewayId);
    } else if (key === "gateways") {
      if (!layers.gateways) next = { ...layers, gateways: true };
    } else if (featureParamValue) {
      const f = features.data?.items.find((x) => x.id === featureParamValue);
      if (!features.data) return;
      if (f && !isFeatureVisible(f, layers)) next = revealFeature(layers, f);
    }
    revealed.current = key;
    if (next) {
      setLayers(next);
      setParams(
        (p) => {
          p.set("revealed", key);
          return p;
        },
        { replace: true },
      );
    }
  }, [
    params,
    setParams,
    selectedId,
    selectedDeviceId,
    selectedGatewayId,
    featureParamValue,
    currentFeatures,
    deviceFeatures,
    features.data,
    groups.data,
    layers,
    allProjects,
    setLayers,
  ]);

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

  const visibleDevices = useMemo(
    () =>
      (deviceFeatures ?? []).filter(
        (f) =>
          f.geometry &&
          (isDeviceShown(f.properties.device_id, layers) ||
            f.properties.device_id === selectedDeviceId),
      ),
    [deviceFeatures, layers, selectedDeviceId],
  );
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    void setDevices(
      map,
      visibleDevices as unknown as GeoJSON.Feature[],
      selectedDeviceId,
    );
  }, [mapRef, ready, visibleDevices, selectedDeviceId]);

  const trackData = tracks.map((q) => q.data);
  const deviceTrackData = deviceTracks.map((q) => q.data);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setTracks(map, [
      ...trackedIds.flatMap((entityId, i) => {
        const data = trackData[i];
        return data
          ? [
              {
                entityId,
                kind: "entity" as const,
                geometry: data.geometry as unknown as GeoJSON.Geometry,
                times: data.times,
              },
            ]
          : [];
      }),
      ...trackedDeviceIds.flatMap((deviceId, i) => {
        const data = deviceTrackData[i];
        return data
          ? [
              {
                entityId: deviceId,
                kind: "device" as const,
                geometry: data.geometry as unknown as GeoJSON.Geometry,
                times: data.times,
              },
            ]
          : [];
      }),
    ]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    mapRef,
    ready,
    trackedIds,
    trackedDeviceIds,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    ...trackData,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    ...deviceTrackData,
  ]);

  const selected = currentFeatures?.find(
    (f) => f.properties.entity_id === selectedId,
  )?.properties;
  const selectedFeature = featureParamValue
    ? features.data?.items.find((f) => f.id === featureParamValue)
    : undefined;
  const selectedDevice = deviceFeatures?.find(
    (f) => f.properties.device_id === selectedDeviceId,
  );
  const selectedDeviceTrack = selectedDeviceId
    ? deviceTracks[trackedDeviceIds.indexOf(selectedDeviceId)]?.data
    : undefined;

  // on a phone the selection panel covers the lower part of the map: bring the selected
  // entity into the free part once, when it is selected or first known
  const phone = useIsPhone();
  const pannedFor = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    const key =
      selectedId ??
      (selectedDeviceId
        ? `device:${selectedDeviceId}`
        : selectedGatewayId
          ? `gateway:${selectedGatewayId}`
          : null);
    if (!map || !ready || !key || !phone) return;
    if (pannedFor.current === key) return;
    const point = selectedId
      ? currentFeatures?.find((f) => f.properties.entity_id === selectedId)
          ?.geometry
      : selectedDeviceId
        ? deviceFeatures?.find(
            (f) => f.properties.device_id === selectedDeviceId,
          )?.geometry
        : (gateways.data?.find((g) => g.id === selectedGatewayId)?.geometry as
            GeoJSON.Point | null | undefined);
    if (!point) return;
    pannedFor.current = key;
    map.easeTo({
      center: point.coordinates as [number, number],
      offset: [0, -Math.round(map.getContainer().clientHeight * 0.2)],
      // a gateway link fits to the gateway; this pan must not undo that zoom
      ...(selectedGatewayId ? { zoom: Math.max(map.getZoom(), 13) } : {}),
      duration: 400,
    });
  }, [
    mapRef,
    ready,
    selectedId,
    selectedDeviceId,
    selectedGatewayId,
    phone,
    currentFeatures,
    deviceFeatures,
    gateways.data,
  ]);

  const tracksOn = trackedIds.length + trackedDeviceIds.length > 0;
  const stripItems: StripItem[] = [
    {
      kind: "menu",
      key: "basemap",
      icon: Layers,
      label: t("Base map"),
      value: basemap,
      options: Object.entries(basemaps).map(([value, b]) => ({
        value,
        label: b.label,
      })),
      onChange: (v) => {
        setBasemap(v as BasemapKey);
        saveBasemap(v as BasemapKey);
      },
    },
    {
      key: "layers",
      icon: ListTree,
      label: t("Layers"),
      active: panelOpen,
      onClick: () => setPanelOpen(!panelOpen),
    },
    {
      key: "tracks",
      icon: Route,
      label: tracksOn
        ? t("Tracks, {{length}}", { length: trackLengthLabel })
        : t("Show a track from an entity or device panel"),
      active: tracksOn && !tracksCardHidden,
      disabled: !tracksOn,
      badge: trackedIds.length + trackedDeviceIds.length,
      onClick: () => setTracksCardHidden((h) => !h),
    },
    {
      key: "draw",
      icon: PenLine,
      label: canEdit
        ? tool === "draw"
          ? t("Stop drawing")
          : t("Draw a feature")
        : t("Drawing features needs the project admin role"),
      active: tool === "draw",
      disabled: !canEdit,
      onClick: () => (tool === "draw" ? endTool() : setTool("draw")),
    },
    {
      key: "measure",
      icon: Ruler,
      label: tool === "measure" ? t("Stop measuring") : t("Measure"),
      active: tool === "measure",
      onClick: () => (tool === "measure" ? endTool() : setTool("measure")),
    },
    ...(maptilerKey
      ? [
          {
            key: "terrain",
            icon: Mountain,
            label: terrainOn ? t("Flat map") : t("3D terrain"),
            active: terrainOn,
            onClick: toggleTerrain,
          } satisfies StripItem,
        ]
      : []),
    {
      key: "heat",
      icon: Flame,
      label: heatOn
        ? t("Heatmaps")
        : t("Show a heatmap from an entity or device panel"),
      active: heatOn && !heatCardHidden,
      disabled: !heatOn,
      badge: heatIds.length + heatDeviceIds.length,
      onClick: () => setHeatCardHidden((h) => !h),
    },
  ];

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={container} className="absolute! inset-0 z-0" />
      {/* the counts, the one thing left in the top left (decision D137) */}
      <div className="pointer-events-none absolute top-3 left-3 z-10 flex max-w-[calc(100%-5rem)] flex-wrap gap-2">
        {current.data && (
          <Badge variant="secondary" className="bg-card">
            {visibleFeatures &&
            visibleFeatures.length !== currentFeatures?.length
              ? `${visibleFeatures.length} / `
              : ""}
            {current.data.total} {t("entities")}
            {current.data.use_tiles ? ", tiles" : ""}
            {visibleDevices.length > 0
              ? `, ${t("{{count}} devices", { count: visibleDevices.length })}`
              : ""}
          </Badge>
        )}
        {events.data && events.data.features.length > 0 && (
          <Badge
            variant="secondary"
            className="pointer-events-auto cursor-pointer bg-card"
            onClick={() => void navigate(`/projects/${projectId}/rules/events`)}
          >
            {events.data.features.length} {t("events, 24 h")}
          </Badge>
        )}
      </div>
      {/* the control strip, rendered into the map's own top right stack */}
      {stripHost &&
        createPortal(<ControlStrip items={stripItems} />, stripHost)}
      {/* the right column: cards, the layers panel and the object panel open from the right edge
          under the strip on desktop and from the bottom on a phone */}
      <div className="pointer-events-none absolute right-14 bottom-2 left-2 z-10 flex max-h-[70%] flex-col gap-2 sm:top-3 sm:bottom-3 sm:left-auto sm:max-h-none sm:w-[22rem] [&>*]:pointer-events-auto">
        {tool && (
          <DrawBar
            purpose={tool}
            kind={drawKind}
            geometry={drawn}
            onKind={changeDrawKind}
            onSave={() => setSaveOpen(true)}
            onCancel={endTool}
          />
        )}
        {tracksOn && !tracksCardHidden && (
          <TracksCard
            count={trackedIds.length + trackedDeviceIds.length}
            points={trackPoints}
            length={trackLength}
            settingsOpen={trackSettingsOpen}
            onToggleSettings={() => setTrackSettingsOpen((o) => !o)}
            onClear={() => {
              setParams(
                (p) => {
                  p.delete("tracks");
                  p.delete("device_tracks");
                  return p;
                },
                { replace: true },
              );
              setTrackSettingsOpen(false);
            }}
          />
        )}
        {trackSettingsOpen && tracksOn && (
          <TrackSettingsPanel
            length={trackLength}
            onChange={setTrackLength}
            onClose={() => setTrackSettingsOpen(false)}
          />
        )}
        {heatOn && !heatCardHidden && (
          <HeatCard
            count={heatIds.length + heatDeviceIds.length}
            points={heatPoints.data?.returned ?? 0}
            capped={heatPoints.data?.capped ?? false}
            devicesScanned={heatPoints.data?.devices_scanned ?? 0}
            devicesTotal={heatPoints.data?.devices_total ?? 0}
            hours={heat.hours}
            loading={heatPoints.isPending && heatPoints.fetchStatus !== "idle"}
            settingsOpen={heatSettingsOpen}
            onToggleSettings={() => setHeatSettingsOpen((o) => !o)}
            onClear={() => {
              setHeatLists([], []);
              setHeatSettingsOpen(false);
            }}
          />
        )}
        {heatOn && heatSettingsOpen && (
          <HeatSettingsPanel
            settings={heat}
            onChange={setHeat}
            onClose={() => setHeatSettingsOpen(false)}
          />
        )}
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
            coverageError={
              layers.coverage && coverage.isError
                ? coverage.error.message
                : undefined
            }
            onRetryCoverage={() => void coverage.refetch()}
            choices={layers}
            trackedIds={trackedIds}
            trackLabel={trackLengthLabel}
            heatIds={heatIds}
            heatDeviceIds={heatDeviceIds}
            onToggleHeat={toggleHeat}
            onToggleDeviceHeat={toggleDeviceHeat}
            devices={(deviceFeatures ?? []).map((f) => f.properties)}
            projects={
              allProjects
                ? (projectList.data?.items ?? []).map((p) => ({
                    id: p.id,
                    name: p.name,
                  }))
                : undefined
            }
            trackedDeviceIds={trackedDeviceIds}
            onPickDevice={(id) => {
              selectDevice(id);
              const f = deviceFeatures?.find(
                (x) => x.properties.device_id === id,
              );
              if (f?.geometry && mapRef.current)
                mapRef.current.easeTo({
                  center: f.geometry.coordinates as [number, number],
                  zoom: Math.max(mapRef.current.getZoom(), 12),
                });
            }}
            onToggleDeviceTrack={(id) =>
              setTrackedDevices(
                trackedDeviceIds.includes(id)
                  ? trackedDeviceIds.filter((x) => x !== id)
                  : [...trackedDeviceIds, id],
                trackLength,
              )
            }
            onChange={setLayers}
            onClose={() => setPanelOpen(false)}
            onToggleTrack={(id) =>
              setTracked(
                trackedIds.includes(id)
                  ? trackedIds.filter((x) => x !== id)
                  : [...trackedIds, id],
                trackLength,
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
                  (x.properties as unknown as EventFeatureProperties)
                    .event_id === id,
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
          <EntityPanel
            props={selected}
            projectId={projectId}
            allProjects={allProjects}
            projectName={projectName}
            now={now}
            wasHidden={revealNote === `entity:${selected.entity_id}`}
            onClose={() => select(null)}
            tracked={trackedIds.includes(selected.entity_id)}
            trackLengthLabel={trackLengthLabel}
            track={selectedTrack}
            heat={heatIds.includes(selected.entity_id)}
            onToggleHeat={() => toggleHeat(selected.entity_id)}
            onToggleTrack={() =>
              setTracked(
                trackedIds.includes(selected.entity_id)
                  ? trackedIds.filter((x) => x !== selected.entity_id)
                  : [...new Set([...trackedIds, selected.entity_id])],
                trackLength,
              )
            }
          />
        )}
        {!selected && selectedDevice && (
          <DevicePanel
            props={selectedDevice.properties}
            projectId={projectId}
            allProjects={allProjects}
            projectName={projectName}
            now={now}
            wasHidden={
              revealNote === `device:${selectedDevice.properties.device_id}`
            }
            onClose={() => selectDevice(null)}
            tracked={trackedDeviceIds.includes(
              selectedDevice.properties.device_id,
            )}
            trackLengthLabel={trackLengthLabel}
            track={selectedDeviceTrack}
            heat={heatDeviceIds.includes(selectedDevice.properties.device_id)}
            onToggleHeat={() =>
              toggleDeviceHeat(selectedDevice.properties.device_id)
            }
            onToggleTrack={() =>
              setTrackedDevices(
                trackedDeviceIds.includes(selectedDevice.properties.device_id)
                  ? trackedDeviceIds.filter(
                      (x) => x !== selectedDevice.properties.device_id,
                    )
                  : [
                      ...new Set([
                        ...trackedDeviceIds,
                        selectedDevice.properties.device_id,
                      ]),
                    ],
                trackLength,
              )
            }
          />
        )}
        {!selected && !selectedDevice && selectedGatewayId && (
          <GatewayPanel
            projectId={projectId}
            gatewayId={selectedGatewayId}
            allProjects={allProjects}
            serverAdmin={Boolean(user?.is_superuser)}
            now={now}
            wasHidden={revealNote === `gateway:${selectedGatewayId}`}
            onClose={() => selectGateway(null)}
            choices={layers}
            coverage={layers.coverage ? coverage.data : undefined}
            onChange={setLayers}
          />
        )}
        {!selected &&
          !selectedDevice &&
          !selectedGatewayId &&
          selectedPoint && (
            <PointPanel
              projectId={projectId}
              ownerId={selectedPoint.ownerId}
              kind={
                trackedDeviceIds.includes(selectedPoint.ownerId)
                  ? "device"
                  : "entity"
              }
              time={selectedPoint.time}
              onClose={() => selectPoint(null)}
              onOpenSourceEvent={(id, ingestedAt) =>
                setSourceEvent({ id, ingestedAt })
              }
              onOpenTrace={setTrace}
            />
          )}
        {!selected &&
          !selectedDevice &&
          !selectedGatewayId &&
          !selectedPoint &&
          selectedFeature && (
            <FeaturePanel
              feature={selectedFeature}
              projectId={projectId}
              canWriteRules={canEdit}
              wasHidden={revealNote === `feature:${selectedFeature.id}`}
              onClose={() => selectFeature(null)}
            />
          )}
      </div>
      <SaveFeatureDialog
        open={saveOpen}
        geometry={drawn}
        pending={createFeature.isPending}
        error={createFeature.error?.message ?? null}
        onOpenChange={setSaveOpen}
        onSave={(values) => createFeature.mutate(values)}
      />
      <SourceEventDialog
        id={sourceEvent?.id ?? null}
        ingestedAt={sourceEvent?.ingestedAt ?? null}
        onClose={() => setSourceEvent(null)}
      />
      <TraceDialog traceId={trace} onClose={() => setTrace(null)} />
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
