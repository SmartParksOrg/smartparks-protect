import { useTranslation } from "react-i18next";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Compass,
  Flame,
  Layers,
  ListTree,
  LocateFixed,
  Minus,
  Mountain,
  PenLine,
  Plus,
  Route,
  Ruler,
} from "lucide-react";
import * as maplibregl from "maplibre-gl";
import { toast } from "sonner";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { fenceSectionFeatures } from "@/lib/fence";
import type {
  CoverageResponse,
  NetworkLocationsResponse,
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
  ensureCoverageLayers,
  ensureDeviceLayers,
  ensureEntityLayers,
  ensureEventLayers,
  ensureFeatureLayers,
  ensureGatewayLayers,
  ensureHeatLayer,
  ensureNetworkLocationLayers,
  ensureTrackLayers,
  type EntityFeatureProperties,
  type EventFeatureProperties,
  raiseMarkers,
  setCoverage,
  setDevices,
  setEntities,
  setEvents,
  setFeatures,
  setGateways,
  setHeatPaint,
  setHeatPoints,
  setNetworkLocations,
  setSelectedTrackPoint,
  setTracks,
  SOURCES,
  trackPointKey,
} from "@/components/map/layers";
import {
  coverageGatewayIds,
  DEFAULT_LAYERS,
  isDeviceShown,
  isEventVisible,
  isFeatureVisible,
  isGatewayVisible,
  isVisible,
  type LayerChoices,
  revealDevice,
  revealEntity,
  revealFeature,
  revealGateway,
} from "@/components/map/layerChoices";
import { ControlStrip, type StripItem } from "@/components/map/ControlStrip";
import { FeedPanel } from "@/components/map/FeedPanel";
import { createSettler, isNewer } from "@/components/map/live";
import { type LocateStatus, startLocate } from "@/components/map/locate";
import {
  type DrawKind,
  type DrawSession,
  type DrawState,
  EMPTY_DRAW,
  createDrawSession,
} from "@/components/map/draw";
import {
  DrawBar,
  SaveFeatureDialog,
  type SaveFeatureValues,
} from "@/components/map/DrawBar";
import {
  ensureGhostLayers,
  heldByEditor,
  removeGhostLayers,
  setGhosts,
  shapeParts,
  type ProposedArea,
} from "@/components/map/propose";
import {
  bindBoxGestures,
  ensureBoxLayer,
  readVerdict,
  setBox,
  type ReadBox,
} from "@/components/map/proposeBox";
import { useUnionAreas } from "@/hooks/useCombineAreas";
import { useProposeArea } from "@/hooks/useProposeArea";
import { FeaturePanel } from "@/components/map/FeaturePanel";
import { geometryBounds } from "@/components/map/fit";
import { isProjectSwitch, rememberProject } from "@/components/map/mapSession";
import {
  DEFAULT_HEAT,
  type HeatSettings,
  parseHeatSettings,
} from "@/components/map/heat";
import { locationFeatures } from "@/components/map/networkLocations";
import { HeatCard, HeatSettingsPanel } from "@/components/map/HeatSettings";
import { GatewayPanel } from "@/components/map/GatewayPanel";
import { LayerPanel } from "@/components/map/LayerPanel";
import { DevicePanel, EntityPanel } from "@/components/map/MapObjectPanel";
import { PointPanel } from "@/components/map/PointPanel";
import { StatePanel } from "@/components/map/StatePanel";
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
import {
  type FeedItem,
  feedPosition,
  newestCreatedAt,
  unreadCount,
} from "@/lib/feed";
import { imprecise } from "@/lib/accuracy";
import { circleRing } from "@/lib/geodesy";
import { isAllProjects } from "@/lib/scope";
import {
  useAnalysisModules,
  usePermissions,
  useProjects,
} from "@/hooks/useProjects";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { useTheme } from "@/hooks/useTheme";

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

/** Where a project's map was left: longitude, latitude, zoom. */
type MapView = [number, number, number];

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

const NO_FEED_ITEMS: FeedItem[] = [];

/**
 * Live map (architecture 11 and 13). Entities come from the current-state endpoint (bounded),
 * updates arrive over the WebSocket, and the page drives every layer (entities, devices,
 * features, events, gateways, coverage, network locations, tracks and heatmaps), the two
 * control strips (the tools top right, zoom and locate bottom right), the Layers and Feed
 * buttons top left, the draw and measure session and the object panels. The container has
 * `z-0` so MapLibre's internals never paint over the app (z-index ladder).
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
  // `?point=<owner>,<time>`; a `device:` prefix names a device's own fix, the older form
  // without it is an entity's, or a device's while its track is on
  const selectedPoint = useMemo(() => {
    const raw = params.get("point");
    if (!raw) return null;
    const comma = raw.indexOf(",");
    if (comma < 0) return null;
    const owner = raw.slice(0, comma);
    const kind = owner.startsWith("device:") ? ("device" as const) : null;
    return {
      ownerId: kind ? owner.slice("device:".length) : owner,
      kind,
      time: raw.slice(comma + 1),
    };
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
  // where the person left the map, per project (Tim, 2026-09-20): the next visit opens there
  // instead of fitting to everything; three numbers per project on the account
  const [mapViews, setMapViews] = usePreference<Record<string, MapView>>(
    "map_view",
    {},
  );
  const rememberedView = projectId ? mapViews[projectId] : undefined;
  // which project's map has been placed, by the fit or by the remembered view; until then
  // nothing about the view is worth remembering
  const placed = useRef<string | null>(null);
  const container = useRef<HTMLDivElement | null>(null);
  const { resolved: resolvedTheme } = useTheme();
  const { mapRef, ready, stripHost, zoomHost } = useMap(
    container,
    basemapStyle(basemap, basemaps, resolvedTheme === "dark"),
    [31.5, -24.9],
    6,
  );
  const client = useQueryClient();
  // following (Tim, 2026-09-15): while an entity or a device is selected the map keeps it in
  // view as new positions arrive; a drag by hand pauses that for this selection, the Follow
  // button resumes it, and another selection starts following again
  const [followPausedFor, setFollowPausedFor] = useState<string | null>(null);
  // a burst of positions (a raw log decoded now) refreshes the tracks and heatmaps once
  const settle = useMemo(() => createSettler(5_000), []);
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
          if (open) {
            p.set("layers", "1");
            p.delete("feed");
          } else p.delete("layers");
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );
  // the feed (decisions D177 to D180): `?feed=1`, one of the two panels open at a time
  const feedOpen = params.get("feed") === "1";
  const setFeedOpen = useCallback(
    (open: boolean) =>
      setParams(
        (p) => {
          if (open) {
            p.set("feed", "1");
            p.delete("layers");
          } else p.delete("feed");
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );
  const feed = useQuery({
    queryKey: queryKeys.events(projectId, { limit: 100 }),
    queryFn: () =>
      api.get<PageType<FeedItem>>(`/api/v1/projects/${projectId}/events`, {
        query: { limit: 100 },
      }),
    refetchInterval: 60_000,
  });
  const feedItems = feed.data?.items ?? NO_FEED_ITEMS;
  const [feedSeen, setFeedSeen] = usePreference<Record<string, string>>(
    "feed_seen",
    {},
  );
  const seenUpTo = feedSeen[projectId] ?? null;
  const unread = unreadCount(feedItems, seenUpTo);
  // the rows stay marked as unread against the mark of the moment the panel opened, while
  // the stored mark moves on so the badge clears
  const [feedMarkAtOpen, setFeedMarkAtOpen] = useState<string | null>(null);
  // the first visit starts at the newest item; an open panel keeps the mark at the newest
  useEffect(() => {
    if (!feed.data) return;
    const newest = newestCreatedAt(feedItems) ?? new Date().toISOString();
    if (seenUpTo === null || (feedOpen && newest > seenUpTo))
      setFeedSeen({ ...feedSeen, [projectId]: newest });
  }, [
    feed.data,
    feedItems,
    feedOpen,
    feedSeen,
    seenUpTo,
    projectId,
    setFeedSeen,
  ]);
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
  // what the enabled layers actually put on the map (Tim, 2026-09-21): the entities and the
  // devices that are shown, the gateways of the gateway layer and the project's features.
  // The fit uses this, so choosing a project brings into view what the person can see there
  // rather than everything the project happens to hold.
  const shownOnMap = useMemo(
    () => [
      ...(visibleFeatures ?? []),
      ...visibleDevices,
      ...(gateways.data ?? []).filter(
        (g) => g.geometry && isGatewayVisible(g.id, layers, g.status),
      ),
      ...(features.data?.items ?? []).filter(
        (f) => f.geometry && isFeatureVisible(f, layers),
      ),
    ],
    [visibleFeatures, visibleDevices, gateways.data, features.data, layers],
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
  // network locations (decisions D162 and D163): where the networks placed the devices over the
  // coverage period, circles of their radius; a small preference field switches them on
  const networkLocationParams = useMemo(
    () => ({ bbox: viewport?.bbox, hours: layers.coverage_hours }),
    [viewport, layers.coverage_hours],
  );
  const networkLocations = useQuery({
    queryKey: queryKeys.networkLocations(projectId, networkLocationParams),
    queryFn: ({ signal }) =>
      api.get<NetworkLocationsResponse>(
        `/api/v1/projects/${projectId}/map/network-locations`,
        { query: networkLocationParams, signal },
      ),
    enabled: Boolean(layers.network_locations) && viewport !== null,
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
    "state",
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
    (ownerId: string | null, time?: string, kind?: "entity" | "device") =>
      selectOnly(
        "point",
        ownerId && time
          ? `${kind === "device" ? "device:" : ""}${ownerId},${time}`
          : null,
      ),
    [selectOnly],
  );
  const selectFeature = useCallback(
    (id: string | null) => selectOnly("feature", id),
    [selectOnly],
  );
  // the last status of a device (`?state=<device>`), opened from the entity and device panels
  const selectedStateDevice = params.get("state");
  const selectState = useCallback(
    (id: string | null) => selectOnly("state", id),
    [selectOnly],
  );

  const phone = useIsPhone();
  // On a phone the panels share one short column (Tim, 2026-09-13): a selection closes the
  // layers panel and the feed, and opening either of them clears the selection, so whatever
  // was asked for last has the room. Desktop keeps them side by side.
  const selectionKey = [
    "entity",
    "device",
    "gateway",
    "state",
    "point",
    "feature",
  ]
    .map((k) => params.get(k) ?? "")
    .join("|");
  const panelsBefore = useRef({ selectionKey, panelOpen, feedOpen });
  useEffect(() => {
    const before = panelsBefore.current;
    panelsBefore.current = { selectionKey, panelOpen, feedOpen };
    if (!phone) return;
    const selected = selectionKey.replace(/\|/g, "") !== "";
    const newSelection = selected && selectionKey !== before.selectionKey;
    const newPanel =
      (panelOpen && !before.panelOpen) || (feedOpen && !before.feedOpen);
    if (newSelection && (panelOpen || feedOpen)) {
      setParams(
        (p) => {
          p.delete("layers");
          p.delete("feed");
          return p;
        },
        { replace: true },
      );
    } else if (newPanel && selected) {
      setParams(
        (p) => {
          for (const k of SELECTION_PARAMS) p.delete(k);
          return p;
        },
        { replace: true },
      );
    }
    // the list is a constant
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phone, selectionKey, panelOpen, feedOpen, setParams]);

  // drawing and measuring (decisions D139 and D141): a tool is transient, not in the URL
  const { can } = usePermissions(projectId);
  const analysisModules = useAnalysisModules(projectId);
  const canEdit = can("features:write");
  const [tool, setTool] = useState<"draw" | "measure" | null>(null);
  const [drawKind, setDrawKind] = useState<DrawKind>("polygon");
  const [drawn, setDrawn] = useState<DrawState>(EMPTY_DRAW);
  const [saveOpen, setSaveOpen] = useState(false);
  const drawSession = useRef<DrawSession | null>(null);
  // propose mode (phase 33): a click asks what encloses it, a candidate goes into the editor
  const [proposing, setProposing] = useState(false);
  const [askedBy, setAskedBy] = useState<"box" | "name">("box");
  // a shape the drawing editor cannot hold, kept as it came (decision D274)
  const [kept, setKept] = useState<{
    geometry: GeoJSON.Geometry;
    parts: number;
    holes: number;
  } | null>(null);
  const proposal = useProposeArea(projectId);
  const endTool = useCallback(() => {
    setTool(null);
    setSaveOpen(false);
    setProposing(false);
    setKept(null);
  }, []);
  const createFeature = useMutationToast({
    // a circle is kept as its polygon with the centre and radius in the attributes (D172)
    mutationFn: (values: SaveFeatureValues) =>
      api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
        body: drawn.circle
          ? {
              ...values,
              geometry: {
                type: "Polygon",
                coordinates: [
                  circleRing(drawn.circle.centre, drawn.circle.radius_m),
                ],
              },
              attributes: {
                shape: "circle",
                centre: drawn.circle.centre,
                radius_m: Math.round(drawn.circle.radius_m),
              },
            }
          : { ...values, geometry: kept?.geometry ?? drawn.geometry },
      }),
    invalidate: [queryKeys.features(projectId)],
    success: t("Feature created"),
    onSuccess: (created) => {
      endTool();
      selectFeature(created.id);
    },
  });

  const followKey = selectedId
    ? `entity:${selectedId}`
    : selectedDeviceId
      ? `device:${selectedDeviceId}`
      : null;
  const following = followKey !== null && followPausedFor !== followKey;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !followKey) return;
    const onDrag = () => setFollowPausedFor(followKey);
    map.on("dragstart", onDrag);
    return () => {
      map.off("dragstart", onDrag);
    };
  }, [mapRef, ready, followKey]);

  // live updates: patch the cached current state, follow the selection, refresh the tracks
  // and the heatmaps
  useProjectStream(projectId, (message) => {
    if (message.topic === "position.created") {
      const time = message.time as string;
      const entityId = message.entity_id as string | null;
      const deviceId = message.device_id as string | null;
      const coordinates: [number, number] = [
        message.longitude as number,
        message.latitude as number,
      ];
      // a position older than the one shown (a raw log decoded now) moves nothing
      const shownEntity = entityId
        ? (
            client.getQueryData<CurrentState>(queryKeys.currentState(projectId))
              ?.features as unknown as CurrentFeature[] | undefined
          )?.find((f) => f.properties.entity_id === entityId)
        : undefined;
      const shownDevice = deviceId
        ? (
            client.getQueryData<CurrentState>(queryKeys.mapDevices(projectId))
              ?.features as unknown as DeviceFeature[] | undefined
          )?.find((f) => f.properties.device_id === deviceId)
        : undefined;
      const entityFresh =
        Boolean(entityId) &&
        isNewer(shownEntity?.properties.position_time, time);
      const deviceFresh =
        Boolean(deviceId) &&
        isNewer(shownDevice?.properties.position_time, time);
      if (entityFresh)
        client.setQueryData<CurrentState>(
          queryKeys.currentState(projectId),
          (old) => {
            if (!old) return old;
            const features = (old.features as unknown as CurrentFeature[]).map(
              (f) =>
                f.properties.entity_id === entityId
                  ? {
                      ...f,
                      geometry: { type: "Point" as const, coordinates },
                      properties: {
                        ...f.properties,
                        last_seen_at: time,
                        position_time: time,
                        device_id: deviceId,
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
      if (deviceFresh)
        client.setQueryData<CurrentState>(
          queryKeys.mapDevices(projectId),
          (old) => {
            if (!old) return old;
            const features = (old.features as unknown as DeviceFeature[]).map(
              (f) =>
                f.properties.device_id === deviceId
                  ? {
                      ...f,
                      geometry: { type: "Point" as const, coordinates },
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
      // the selected object stays in view while it moves
      if (
        following &&
        ((selectedId && entityId === selectedId && entityFresh) ||
          (selectedDeviceId && deviceId === selectedDeviceId && deviceFresh))
      )
        mapRef.current?.easeTo({ center: coordinates, duration: 800 });
      if (
        (entityId && trackedIds.includes(entityId)) ||
        (deviceId && trackedDeviceIds.includes(deviceId))
      )
        settle("track", () => {
          void client.invalidateQueries({
            queryKey: ["projects", projectId, "track"],
          });
        });
      if (
        (entityId && heatIds.includes(entityId)) ||
        (deviceId && heatDeviceIds.includes(deviceId))
      )
        settle("heat", () => {
          void client.invalidateQueries({
            queryKey: ["projects", projectId, "map", "heat"],
          });
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
      void client.invalidateQueries({ queryKey: ["events", projectId] });
    }
    // a new alert announces itself while the map is open (decision D180)
    if (
      message.topic === "alert.created" &&
      typeof message.event_id === "string"
    ) {
      const eventId = message.event_id;
      toast.warning(String(message.title ?? t("Alert")), {
        description: String(message.severity ?? ""),
        action: {
          label: t("Show"),
          onClick: () =>
            setParams(
              (p) => {
                p.set("event", eventId);
                return p;
              },
              { replace: true },
            ),
        },
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
    ensureNetworkLocationLayers(map);
    ensureHeatLayer(map);
    ensureTrackLayers(map);
    ensureEventLayers(map);
    raiseMarkers(map);
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
      setDrawn(EMPTY_DRAW);
    };
    // the kind is applied through `begin` in changeDrawKind, not by recreating the session
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapRef, ready, tool]);
  const changeDrawKind = (kind: DrawKind) => {
    setDrawKind(kind);
    setProposing(false);
    proposal.reset();
    drawSession.current?.begin(kind);
  };
  const toggleProposing = () => {
    const next = !proposing;
    setProposing(next);
    setReading(null);
    proposal.cancel();
    if (next) drawSession.current?.idle();
    else drawSession.current?.begin(drawKind);
  };
  // a shape terra-draw can hold goes into the drawing session and is corrected like any
  // polygon; a zone in several pieces, or one with an enclave inside it, is kept as it came,
  // drawn as an outline and saved from there (decision D274)
  const takeShape = (geometry: GeoJSON.Geometry) => {
    setDrawKind("polygon");
    setProposing(false);
    proposal.reset();
    // into the editor when it can hold the shape and says it took it; a refusal there is
    // silent, and used to leave Save as feature grey with nothing to save (Tim, 2026-09-21)
    if (
      heldByEditor(geometry) &&
      drawSession.current?.load("polygon", geometry) === true
    ) {
      setKept(null);
      return;
    }
    // the session holds one polygon of one ring and clears itself as it goes, so a shape it
    // cannot hold is kept here and saved from here (Tim, 2026-09-21: after Use on an area with
    // enclaves, Save as feature stayed grey and nothing could be saved at all)
    drawSession.current?.clear();
    setKept({ geometry, ...shapeParts(geometry) });
  };
  const pickCandidate = (candidate: ProposedArea) =>
    takeShape(candidate.geometry);
  // several ticked areas as one zone (decision D274): the union is worked out by the API
  const union = useUnionAreas(projectId);
  const combineCandidates = (chosen: ProposedArea[]) => {
    union.mutate(
      { geometries: chosen.map((c) => c.geometry) },
      { onSuccess: (combined) => takeShape(combined.geometry) },
    );
  };
  // a name is looked for in what the map shows, so panning to the reserve is enough (D273)
  const searchByName = (name: string) => {
    const map = mapRef.current;
    if (!map) return;
    const view = map.getBounds();
    setReading(null);
    setAskedBy("name");
    proposal.ask({
      kind: "name",
      name,
      bounds: [
        [view.getWest(), view.getSouth()],
        [view.getEast(), view.getNorth()],
      ],
    });
  };
  // while proposing, a click reads the default box around the point and a drag reads the box
  // it draws (decision D277); the box is on the map before it is read, and a box past the
  // limit is refused here rather than sent
  const [reading, setReading] = useState<ReadBox | null>(null);
  const [preview, setPreview] = useState<ReadBox | null>(null);
  const readBox = useCallback(
    (box: ReadBox) => {
      if (proposal.isPending) return; // one read at a time (decision D277)
      setReading(box);
      setAskedBy("box");
      if (readVerdict(box).tooLarge) return;
      proposal.ask({ kind: "box", box });
    },
    // the mutation object is stable enough for a gesture
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !proposing) return;
    map.getCanvas().style.cursor = "crosshair";
    ensureBoxLayer(map);
    const stop = bindBoxGestures(map, {
      onPreview: setPreview,
      onGesture: ({ box }) => readBox(box),
    });
    return () => {
      stop();
      setPreview(null);
      map.getCanvas().style.cursor = "";
    };
  }, [mapRef, ready, proposing, readBox]);
  const proposalPending = proposal.isPending;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!proposing) {
      if (map.getLayer("propose-box-fill")) setBox(map, null);
      return;
    }
    ensureBoxLayer(map);
    setBox(map, preview ?? (proposalPending ? reading : null));
  }, [mapRef, ready, proposing, preview, reading, proposalPending]);
  const candidates = proposal.data?.candidates;
  const ghosts = useMemo(
    () =>
      kept
        ? [
            {
              kind: "osm",
              name: "",
              geometry: kept.geometry,
              area_m2: 0,
              clipped: false,
            },
          ]
        : proposing
          ? (candidates ?? [])
          : [],
    [proposing, candidates, kept],
  );
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!tool) {
      removeGhostLayers(map);
      return;
    }
    ensureGhostLayers(map);
    setGhosts(map, ghosts);
  }, [mapRef, ready, tool, ghosts]);

  // Locate (decision D173): a toggle that watches the browser's position and follows it
  const [locate, setLocate] = useState<LocateStatus>("off");
  const locateSession = useRef<ReturnType<typeof startLocate> | null>(null);
  const toggleLocate = useCallback(() => {
    const map = mapRef.current;
    if (locateSession.current) {
      locateSession.current.stop();
      locateSession.current = null;
      return;
    }
    if (!map) return;
    locateSession.current = startLocate(map, setLocate);
  }, [mapRef]);
  useEffect(() => {
    if (locate === "denied") {
      locateSession.current?.stop();
      locateSession.current = null;
      toast.error(
        t(
          "Your position is not available; check the browser's location permission",
        ),
      );
    }
  }, [locate, t]);
  useEffect(
    () => () => {
      locateSession.current?.stop();
      locateSession.current = null;
    },
    [ready],
  );

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
        if (!projectId) return;
        // nothing is remembered until this project's map has been placed (Tim, 2026-09-21):
        // the map starts over southern Africa and the fit waits for the reads, so a view
        // written before then is the starting point, not the person's, and every later visit
        // would open there — which is how a Dutch project ended up opening over Kruger
        if (placed.current !== projectId) return;
        // the view the person sees now is the one the next visit opens with; read the
        // document fresh so a pan never writes an older copy of the other projects' views
        const c = map.getCenter();
        const view: MapView = [
          Number(c.lng.toFixed(5)),
          Number(c.lat.toFixed(5)),
          Number(map.getZoom().toFixed(2)),
        ];
        const known = (useAuthStore.getState().user?.preferences?.map_view ??
          {}) as Record<string, MapView>;
        const before = known[projectId];
        if (before && before.every((v, i) => v === view[i])) return;
        setMapViews({ ...known, [projectId]: view });
      }, 600);
    };
    update();
    map.on("moveend", update);
    return () => {
      map.off("moveend", update);
      if (timer) clearTimeout(timer);
    };
  }, [mapRef, ready, projectId, setMapViews]);

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
    if (!map || !ready) return;
    setNetworkLocations(
      map,
      layers.network_locations && networkLocations.data
        ? locationFeatures(
            networkLocations.data.features as unknown as GeoJSON.Feature[],
          )
        : [],
    );
  }, [mapRef, ready, layers.network_locations, networkLocations.data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !gateways.data) return;
    setGateways(
      map,
      gateways.data
        .filter((g) => g.geometry && isGatewayVisible(g.id, layers, g.status))
        .map((g) => ({
          type: "Feature",
          geometry: g.geometry as unknown as GeoJSON.Geometry,
          properties: {
            gateway_id: g.id,
            name: g.display_name,
            last_seen_at: g.last_seen_at,
            status: g.status,
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

  // fit to the project once per visit, to everything its enabled layers show (phase 19, and
  // Tim, 2026-09-21): a park whose devices have no animal yet, or hardware in the workshop,
  // fits to the devices; a project with only gateways or only zones fits to those. Without a
  // single geometry the view stays where it was. Waits for the reads the layers need, so the
  // fit is not to half of them.
  const fittedProject = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    const waiting =
      current.isPending ||
      devices.isPending ||
      (layers.features && features.isPending) ||
      (layers.gateways && gateways.isPending);
    if (!map || !ready || waiting) return;
    if (fittedProject.current === projectId) return;
    fittedProject.current = projectId;
    // choosing another project fits to it; coming back to this one, or reloading the page,
    // opens where the person left it (decision D275)
    const switched = isProjectSwitch(projectId);
    rememberProject(projectId);
    placed.current = projectId;
    // a link to a gateway or a feature fits to that object instead; a link to an entity or a
    // device with an imprecise position fits its accuracy disc (the selection effect below)
    if (gatewayParam || featureParamValue) return;
    const selectedAccuracy = selectedId
      ? currentFeatures?.find((f) => f.properties.entity_id === selectedId)
          ?.properties.accuracy_m
      : selectedDeviceId
        ? deviceFeatures?.find(
            (f) => f.properties.device_id === selectedDeviceId,
          )?.properties.accuracy_m
        : null;
    if (imprecise(selectedAccuracy)) return;
    // a "show on map" link centres on its object (Tim, 2026-09-15); a plain project visit
    // fits everything
    const selectedPoint = selectedId
      ? currentFeatures?.find((f) => f.properties.entity_id === selectedId)
          ?.geometry
      : selectedDeviceId
        ? deviceFeatures?.find(
            (f) => f.properties.device_id === selectedDeviceId,
          )?.geometry
        : null;
    if (selectedPoint?.type === "Point") {
      map.jumpTo({
        center: selectedPoint.coordinates as [number, number],
        zoom: Math.max(map.getZoom(), 14),
      });
      return;
    }
    // back where the person left this project's map; a switch and a first visit fit instead
    if (rememberedView && !switched) {
      const [lng, lat, zoom] = rememberedView;
      map.jumpTo({ center: [lng, lat], zoom });
      return;
    }
    const bounds = geometryBounds(
      shownOnMap as unknown as {
        geometry: { type: string; coordinates: unknown } | null;
      }[],
    );
    if (bounds)
      map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 0 });
  }, [
    mapRef,
    ready,
    projectId,
    current.isPending,
    devices.isPending,
    features.isPending,
    gateways.isPending,
    layers.features,
    layers.gateways,
    shownOnMap,
    currentFeatures,
    deviceFeatures,
    gatewayParam,
    featureParamValue,
    selectedId,
    selectedDeviceId,
    rememberedView,
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
        next = revealGateway(
          layers,
          selectedGatewayId,
          gateways.data?.find((g) => g.id === selectedGatewayId)?.status,
        );
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
        .flatMap((f) => fenceSectionFeatures(f)),
    );
  }, [mapRef, ready, features.data, layers]);

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

  const selectedEntityFeature = currentFeatures?.find(
    (f) => f.properties.entity_id === selectedId,
  );
  const selected = selectedEntityFeature?.properties;
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
    if (!map || !ready || !key) return;
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
    // an imprecise position (decision D193) is shown with its whole accuracy disc in view, on
    // every screen; a precise one is panned from under the panel on a phone only
    const accuracy = selectedId
      ? currentFeatures?.find((f) => f.properties.entity_id === selectedId)
          ?.properties.accuracy_m
      : selectedDeviceId
        ? deviceFeatures?.find(
            (f) => f.properties.device_id === selectedDeviceId,
          )?.properties.accuracy_m
        : null;
    if (!phone && !imprecise(accuracy)) return;
    pannedFor.current = key;
    if (imprecise(accuracy)) {
      const [lon, lat] = point.coordinates as [number, number];
      const dLat = (accuracy as number) / 111_320;
      const dLon = dLat / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
      const height = map.getContainer().clientHeight;
      map.fitBounds(
        [
          [lon - dLon, lat - dLat],
          [lon + dLon, lat + dLat],
        ],
        {
          padding: {
            top: 60,
            left: 40,
            right: 40,
            bottom: phone ? Math.round(height * 0.45) : 60,
          },
          maxZoom: 17,
          duration: 400,
        },
      );
      return;
    }
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
  // the layout of the controls (decision D174): base map with terrain under it, draw and
  // measure, then tracks and heatmaps only while one is on
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
    // no drawing in the all scope (decision D278): a feature belongs to one project, and that
    // scope reads across every one of them, so there is nothing to save it into. It used to be
    // offered and the save came back as a UUID parse error nobody could act on (Tim, 2026-09-21)
    ...(allProjects
      ? []
      : [
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
          } satisfies StripItem,
        ]),
    {
      key: "measure",
      icon: Ruler,
      label: tool === "measure" ? t("Stop measuring") : t("Measure"),
      active: tool === "measure",
      onClick: () => (tool === "measure" ? endTool() : setTool("measure")),
    },
    ...(tracksOn
      ? [
          {
            key: "tracks",
            icon: Route,
            label: t("Tracks, {{length}}", { length: trackLengthLabel }),
            active: !tracksCardHidden,
            badge: trackedIds.length + trackedDeviceIds.length,
            onClick: () => setTracksCardHidden((h) => !h),
          } satisfies StripItem,
        ]
      : []),
    ...(heatOn
      ? [
          {
            key: "heat",
            icon: Flame,
            label: t("Heatmaps"),
            active: !heatCardHidden,
            badge: heatIds.length + heatDeviceIds.length,
            onClick: () => setHeatCardHidden((h) => !h),
          } satisfies StripItem,
        ]
      : []),
  ];
  const layersItem: StripItem = {
    key: "layers",
    icon: ListTree,
    label: t("Layers"),
    active: panelOpen,
    emphasis: true,
    onClick: () => setPanelOpen(!panelOpen),
  };
  const feedItem: StripItem = {
    key: "feed",
    icon: Bell,
    label: t("Feed"),
    active: feedOpen,
    badge: unread,
    onClick: () => {
      if (!feedOpen) setFeedMarkAtOpen(seenUpTo);
      setFeedOpen(!feedOpen);
    },
  };
  const entityNameOf = (id: string | null | undefined): string | null =>
    id
      ? ((currentFeatures?.find((f) => f.properties.entity_id === id)
          ?.properties.name as string | undefined) ?? null)
      : null;
  const selectFeedItem = (item: FeedItem) => {
    const position = feedPosition(item);
    const map = mapRef.current;
    if (position && map)
      map.easeTo({ center: position, zoom: Math.max(map.getZoom(), 14) });
    setParams(
      (p) => {
        p.set("event", item.id);
        return p;
      },
      { replace: true },
    );
  };
  // zoom, north and locate, our own buttons at the bottom right (decision D173)
  const zoomItems: StripItem[] = [
    {
      key: "zoom-in",
      icon: Plus,
      label: t("Zoom in"),
      onClick: () => mapRef.current?.zoomIn(),
    },
    {
      key: "zoom-out",
      icon: Minus,
      label: t("Zoom out"),
      onClick: () => mapRef.current?.zoomOut(),
    },
    {
      key: "north",
      icon: Compass,
      label: t("Reset north"),
      onClick: () => mapRef.current?.easeTo({ bearing: 0, pitch: 0 }),
    },
    {
      key: "locate",
      icon: LocateFixed,
      label:
        locate === "off" || locate === "denied"
          ? t("Follow my position")
          : locate === "waiting"
            ? t("Waiting for a position")
            : locate === "tracking"
              ? t(
                  "Following stopped by a pan; press again to stop showing the position",
                )
              : t("Stop following my position"),
      active:
        locate === "waiting" || locate === "following" || locate === "tracking",
      onClick: toggleLocate,
    },
  ];

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden">
      <div ref={container} className="absolute! inset-0 z-0" />
      {/* the layers and feed buttons and the events count in the top left (decisions D137, D174, D177); the entity and device count went on 2026-09-12 at Tim's word, the layers panel carries the numbers */}
      <div className="pointer-events-none absolute top-3 left-3 z-10 flex max-w-[calc(100%-5rem)] items-start gap-2 [&>*]:pointer-events-auto">
        <ControlStrip
          items={[layersItem, feedItem]}
          label={t("Layers and feed")}
        />
        <div className="flex flex-wrap gap-2 [&>*]:pointer-events-auto">
          {events.data && events.data.features.length > 0 && (
            <Badge
              variant="secondary"
              className="pointer-events-auto cursor-pointer bg-card"
              onClick={() =>
                void navigate(`/projects/${projectId}/rules/events`)
              }
            >
              {events.data.features.length} {t("events, 24 h")}
            </Badge>
          )}
        </div>
      </div>
      {/* the control strips, rendered into the map's own top right and bottom right stacks */}
      {stripHost &&
        createPortal(<ControlStrip items={stripItems} />, stripHost)}
      {zoomHost &&
        createPortal(
          <ControlStrip items={zoomItems} label={t("Zoom and position")} />,
          zoomHost,
        )}
      {/* the right column: cards, the layers panel and the object panel open from the right edge
          under the strip on desktop and from the bottom on a phone */}
      <div className="pointer-events-none absolute right-14 bottom-2 left-2 z-10 flex max-h-[70%] flex-col gap-2 overflow-hidden sm:top-3 sm:bottom-3 sm:left-auto sm:max-h-none sm:w-[22rem] [&>*]:pointer-events-auto">
        {tool && (
          <DrawBar
            purpose={tool}
            kind={drawKind}
            state={drawn}
            savable={!!kept?.geometry}
            onKind={changeDrawKind}
            onSave={() => setSaveOpen(true)}
            onCancel={endTool}
            propose={{
              active: proposing,
              busy: proposal.isPending,
              proposal: proposal.data ?? null,
              error: proposal.error?.message ?? null,
              asked: askedBy,
              reading: preview ?? reading,
              onToggle: toggleProposing,
              onPick: pickCandidate,
              onSearch: searchByName,
              onCombine: combineCandidates,
              onCancel: proposal.cancel,
              kept: kept ? { parts: kept.parts, holes: kept.holes } : null,
            }}
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
        {trackSettingsOpen && tracksOn && !tracksCardHidden && (
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
        {heatOn && heatSettingsOpen && !heatCardHidden && (
          <HeatSettingsPanel
            settings={heat}
            onChange={setHeat}
            onClose={() => setHeatSettingsOpen(false)}
          />
        )}
        {feedOpen && (
          <FeedPanel
            projectId={projectId}
            items={feedItems}
            seenUpTo={feedMarkAtOpen}
            loading={feed.isPending}
            canWriteAlerts={canEdit}
            entityName={entityNameOf}
            onSelect={selectFeedItem}
            onClose={() => setFeedOpen(false)}
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
            networkLocations={
              layers.network_locations ? networkLocations.data : undefined
            }
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
            onOpenPosition={() =>
              selected.position_time &&
              selectPoint(selected.entity_id, selected.position_time, "entity")
            }
            onOpenState={
              selected.device_id
                ? () => selectState(selected.device_id as string)
                : undefined
            }
            position={
              (selectedEntityFeature?.geometry?.coordinates as
                [number, number] | undefined) ?? null
            }
            tracked={trackedIds.includes(selected.entity_id)}
            trackLengthLabel={trackLengthLabel}
            track={selectedTrack}
            heat={heatIds.includes(selected.entity_id)}
            onToggleHeat={() => toggleHeat(selected.entity_id)}
            following={following}
            onToggleFollow={() =>
              setFollowPausedFor(following ? followKey : null)
            }
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
            onOpenPosition={() =>
              selectedDevice.properties.position_time &&
              selectPoint(
                selectedDevice.properties.device_id,
                selectedDevice.properties.position_time,
                "device",
              )
            }
            onOpenState={() => selectState(selectedDevice.properties.device_id)}
            position={
              (selectedDevice.geometry?.coordinates as
                [number, number] | undefined) ?? null
            }
            tracked={trackedDeviceIds.includes(
              selectedDevice.properties.device_id,
            )}
            trackLengthLabel={trackLengthLabel}
            track={selectedDeviceTrack}
            heat={heatDeviceIds.includes(selectedDevice.properties.device_id)}
            onToggleHeat={() =>
              toggleDeviceHeat(selectedDevice.properties.device_id)
            }
            following={following}
            onToggleFollow={() =>
              setFollowPausedFor(following ? followKey : null)
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
          !selectedPoint &&
          selectedStateDevice && (
            <StatePanel
              projectId={projectId}
              deviceId={selectedStateDevice}
              onClose={() => selectState(null)}
              onOpenSourceEvent={(id, ingestedAt) =>
                setSourceEvent({ id, ingestedAt })
              }
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
                selectedPoint.kind ??
                (trackedDeviceIds.includes(selectedPoint.ownerId)
                  ? "device"
                  : "entity")
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
              grazingHref={
                analysisModules.includes("grazing") &&
                can("analysis:run") &&
                ["zone", "geofence"].includes(selectedFeature.feature_type)
                  ? `/projects/${projectId}/analyze/grazing?area=${selectedFeature.id}`
                  : null
              }
              wasHidden={revealNote === `feature:${selectedFeature.id}`}
              onClose={() => selectFeature(null)}
            />
          )}
      </div>
      <SaveFeatureDialog
        open={saveOpen}
        geometry={drawn.geometry}
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
