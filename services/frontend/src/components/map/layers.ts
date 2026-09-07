import type {
  ExpressionSpecification,
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from "maplibre-gl";

import {
  ensureMarkerImage,
  type MarkerState,
} from "@/components/icons/markers";

export const SOURCES = {
  entities: "entities",
  devices: "devices",
  track: "track",
  features: "features",
  events: "events",
  gateways: "gateways",
  coverage: "coverage",
} as const;

/** Glyphs the OpenFreeMap styles serve; the MapLibre default (Open Sans) is not among them. */
const FONT = ["Noto Sans Regular"];

export interface EntityFeatureProperties {
  entity_id: string;
  /** The entity's project; in the all scope (decision D117) it names the project and links. */
  project_id?: string;
  name: string;
  status: string;
  entity_type: string;
  group: string;
  group_id?: string | null;
  icon_key: string;
  /** Set when the entity has a profile picture (decision D110); its version for the cache. */
  picture_updated_at?: string | null;
  device_id: string | null;
  /** When the device tracking the entity today was assigned to it (track settings). */
  assigned_since?: string | null;
  last_seen_at: string | null;
  position_time: string | null;
  active_alert_count: number;
  health_level?: string | null;
  battery_voltage?: number | null;
  last_status_at?: string | null;
  device_last_seen_at?: string | null;
}

/** A device on the device layer (decision D111): assigned to the project today, with or
 * without an entity; `project_since` starts the "since assignment" track length. */
export interface DeviceFeatureProperties {
  device_id: string;
  project_id?: string;
  name: string;
  serial_number: string | null;
  status: string;
  device_type: string;
  icon_key: string;
  entity_id: string | null;
  entity_name: string | null;
  group_id: string | null;
  project_since: string | null;
  last_seen_at: string | null;
  position_time: string | null;
  health_level?: string | null;
  battery_voltage?: number | null;
  last_status_at?: string | null;
  picture_updated_at?: string | null;
}

const OFFLINE_AFTER_MS = 24 * 3600_000;

export function stateFor(
  props: EntityFeatureProperties,
  selectedId: string | null,
): MarkerState {
  if (props.entity_id === selectedId) return "selected";
  if (props.active_alert_count > 0) return "critical";
  if (
    props.last_seen_at &&
    Date.now() - new Date(props.last_seen_at).getTime() > OFFLINE_AFTER_MS
  )
    return "offline";
  return "normal";
}

/** Add the entity source and layers once; features are pushed with `setEntities`. Click
 * handlers are not bound here: the map outlives a project change on the same page, so a handler
 * registered once would keep the callbacks of the first project. Use `bindEntityClicks` from an
 * effect and call the returned function in its cleanup. */
export function ensureEntityLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.entities)) return;
  map.addSource(SOURCES.entities, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    cluster: true,
    clusterRadius: 48,
    clusterMaxZoom: 14,
    promoteId: "entity_id",
  });
  map.addLayer({
    id: "entity-clusters",
    type: "circle",
    source: SOURCES.entities,
    filter: ["has", "point_count"],
    paint: {
      "circle-color": "#52735E",
      "circle-radius": ["step", ["get", "point_count"], 16, 10, 20, 50, 26],
      "circle-stroke-width": 3,
      "circle-stroke-color": "#ffffff",
    },
  });
  map.addLayer({
    id: "entity-cluster-count",
    type: "symbol",
    source: SOURCES.entities,
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["get", "point_count_abbreviated"],
      "text-size": 12,
      "text-font": FONT,
    },
    paint: { "text-color": "#ffffff" },
  });
  map.addLayer({
    id: "entity-markers",
    type: "symbol",
    source: SOURCES.entities,
    filter: ["!", ["has", "point_count"]],
    layout: {
      "icon-image": ["get", "marker"],
      "icon-size": 0.9,
      "icon-allow-overlap": true,
      "text-field": ["get", "name"],
      "text-size": 11,
      "text-font": FONT,
      "text-offset": [0, 1.8],
      "text-anchor": "top",
      "text-optional": true,
    },
    paint: {
      "text-color": "#1f2a24",
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.2,
    },
  });
  for (const layer of ["entity-markers", "entity-clusters"]) {
    map.on(
      "mouseenter",
      layer,
      () => (map.getCanvas().style.cursor = "pointer"),
    );
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }
}

/** Bind the entity and cluster clicks; the returned function unbinds them. */
export function bindEntityClicks(
  map: MapLibreMap,
  onClick: (props: EntityFeatureProperties) => void,
  onClusterClick: (lngLat: [number, number], clusterId: number) => void,
): () => void {
  const onMarker = (e: MapLayerMouseEvent) => {
    const feature = e.features?.[0];
    if (feature)
      onClick(feature.properties as unknown as EntityFeatureProperties);
  };
  const onCluster = (e: MapLayerMouseEvent) => {
    const feature = e.features?.[0];
    if (!feature) return;
    const geometry = feature.geometry as GeoJSON.Point;
    onClusterClick(
      geometry.coordinates as [number, number],
      feature.properties?.cluster_id as number,
    );
  };
  map.on("click", "entity-markers", onMarker);
  map.on("click", "entity-clusters", onCluster);
  return () => {
    map.off("click", "entity-markers", onMarker);
    map.off("click", "entity-clusters", onCluster);
  };
}

export async function setEntities(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
  selectedId: string | null,
): Promise<void> {
  const source = map.getSource(SOURCES.entities) as GeoJSONSource | undefined;
  if (!source) return;
  const withMarkers: GeoJSON.Feature[] = [];
  for (const feature of features) {
    const props = feature.properties as unknown as EntityFeatureProperties;
    const state = stateFor(props, selectedId);
    const marker = await ensureMarkerImage(map, props.icon_key, state);
    withMarkers.push({
      ...feature,
      properties: { ...feature.properties, marker },
    });
  }
  source.setData({ type: "FeatureCollection", features: withMarkers });
}

export function deviceStateFor(
  props: DeviceFeatureProperties,
  selectedId: string | null,
): MarkerState {
  if (props.device_id === selectedId) return "selected";
  if (props.health_level === "critical") return "critical";
  if (
    props.last_seen_at &&
    Date.now() - new Date(props.last_seen_at).getTime() > OFFLINE_AFTER_MS
  )
    return "offline";
  return "normal";
}

/** The device layer (decision D112): square markers under the entities, so a collar and its
 * animal stay apart. No clustering: the layer is opt-in per device. Add after the entity
 * layers, which it sits beneath. */
export function ensureDeviceLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.devices)) return;
  // clustered like the entities; a device cluster is the inverse of an entity cluster
  // (white with a green ring) and sits a little down and right of it, so a collar cluster
  // and its animals' cluster over the same ground both stay visible
  map.addSource(SOURCES.devices, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    cluster: true,
    clusterRadius: 48,
    clusterMaxZoom: 14,
    promoteId: "device_id",
  });
  map.addLayer(
    {
      id: "device-clusters",
      type: "circle",
      source: SOURCES.devices,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": "#ffffff",
        "circle-radius": ["step", ["get", "point_count"], 14, 10, 18, 50, 24],
        "circle-stroke-width": 3,
        "circle-stroke-color": "#52735E",
        "circle-translate": [10, 10],
      },
    },
    "entity-clusters",
  );
  map.addLayer(
    {
      id: "device-cluster-count",
      type: "symbol",
      source: SOURCES.devices,
      filter: ["has", "point_count"],
      layout: {
        "text-field": ["get", "point_count_abbreviated"],
        "text-size": 11,
        "text-font": FONT,
        "text-offset": [0.9, 0.9],
        "text-allow-overlap": true,
      },
      paint: { "text-color": "#2F4A3A" },
    },
    "entity-clusters",
  );
  map.addLayer(
    {
      id: "device-markers",
      type: "symbol",
      source: SOURCES.devices,
      filter: ["!", ["has", "point_count"]],
      layout: {
        "icon-image": ["get", "marker"],
        "icon-size": 0.75,
        // beside its animal (decision D112), not under it
        "icon-offset": [16, 16],
        "icon-allow-overlap": true,
        "text-field": ["get", "name"],
        "text-size": 10,
        "text-font": FONT,
        "text-offset": [1.2, 2.4],
        "text-anchor": "top",
        "text-optional": true,
      },
      paint: {
        "text-color": "#2F4A3A",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.2,
      },
    },
    "entity-clusters",
  );
  for (const layer of ["device-markers", "device-clusters"]) {
    map.on(
      "mouseenter",
      layer,
      () => (map.getCanvas().style.cursor = "pointer"),
    );
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }
}

/** Bind the device marker click; the returned function unbinds it. */
export function bindDeviceClicks(
  map: MapLibreMap,
  onClick: (props: DeviceFeatureProperties) => void,
  onClusterClick: (lngLat: [number, number], clusterId: number) => void,
): () => void {
  const onMarker = (e: MapLayerMouseEvent) => {
    const feature = e.features?.[0];
    if (feature)
      onClick(feature.properties as unknown as DeviceFeatureProperties);
  };
  const onCluster = (e: MapLayerMouseEvent) => {
    const feature = e.features?.[0];
    if (!feature) return;
    const geometry = feature.geometry as GeoJSON.Point;
    onClusterClick(
      geometry.coordinates as [number, number],
      feature.properties?.cluster_id as number,
    );
  };
  map.on("click", "device-markers", onMarker);
  map.on("click", "device-clusters", onCluster);
  return () => {
    map.off("click", "device-markers", onMarker);
    map.off("click", "device-clusters", onCluster);
  };
}

export async function setDevices(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
  selectedId: string | null,
): Promise<void> {
  const source = map.getSource(SOURCES.devices) as GeoJSONSource | undefined;
  if (!source) return;
  const withMarkers: GeoJSON.Feature[] = [];
  for (const feature of features) {
    const props = feature.properties as unknown as DeviceFeatureProperties;
    const marker = await ensureMarkerImage(
      map,
      props.icon_key,
      deviceStateFor(props, selectedId),
    );
    withMarkers.push({
      ...feature,
      properties: { ...feature.properties, marker },
    });
  }
  source.setData({ type: "FeatureCollection", features: withMarkers });
}

const TRACK_COLORS = [
  "#2F4A3A",
  "#b45309",
  "#1d4ed8",
  "#be185d",
  "#0f766e",
  "#6d28d9",
  "#a16207",
  "#374151",
];

/** A steady colour per entity, so two tracks on the map stay apart. */
export function trackColor(entityId: string): string {
  let hash = 0;
  for (const c of entityId) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  return TRACK_COLORS[hash % TRACK_COLORS.length];
}

export function ensureTrackLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.track)) return;
  map.addSource(SOURCES.track, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer(
    {
      id: "track-line",
      type: "line",
      source: SOURCES.track,
      filter: [
        "all",
        ["==", ["geometry-type"], "LineString"],
        ["!=", ["get", "kind"], "device"],
      ],
      paint: {
        "line-color": ["coalesce", ["get", "color"], "#2F4A3A"],
        "line-width": 3,
        "line-opacity": 0.85,
      },
    },
    "entity-clusters",
  );
  // device tracks are dashed (decision D114), so a collar's path and its animal's stay apart
  map.addLayer(
    {
      id: "track-line-device",
      type: "line",
      source: SOURCES.track,
      filter: [
        "all",
        ["==", ["geometry-type"], "LineString"],
        ["==", ["get", "kind"], "device"],
      ],
      paint: {
        "line-color": ["coalesce", ["get", "color"], "#2F4A3A"],
        "line-width": 2.5,
        "line-opacity": 0.85,
        "line-dasharray": [2, 1.5],
      },
    },
    "entity-clusters",
  );
  map.addLayer(
    {
      id: "track-points",
      type: "circle",
      source: SOURCES.track,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 3,
        "circle-color": "#ffffff",
        "circle-stroke-color": ["coalesce", ["get", "color"], "#2F4A3A"],
        "circle-stroke-width": 1.5,
      },
    },
    "entity-clusters",
  );
}

export interface TrackLayer {
  /** The entity or the device the track belongs to; the colour comes from it. */
  entityId: string;
  kind?: "entity" | "device";
  geometry: GeoJSON.Geometry;
  times: string[];
}

/** Every track shown at once, each in its entity's colour. */
export function setTracks(map: MapLibreMap, tracks: TrackLayer[]): void {
  const source = map.getSource(SOURCES.track) as GeoJSONSource | undefined;
  if (!source) return;
  const features: GeoJSON.Feature[] = [];
  for (const track of tracks) {
    const color = trackColor(track.entityId);
    features.push({
      type: "Feature",
      geometry: track.geometry,
      properties: {
        color,
        entity_id: track.entityId,
        kind: track.kind ?? "entity",
      },
    });
    const coordinates =
      track.geometry.type === "LineString"
        ? track.geometry.coordinates
        : track.geometry.type === "MultiPoint"
          ? track.geometry.coordinates
          : [];
    coordinates.forEach((c, i) =>
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: c },
        properties: { color, time: track.times[i] },
      }),
    );
  }
  source.setData({ type: "FeatureCollection", features });
}

export function ensureFeatureLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.features)) return;
  map.addSource(SOURCES.features, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer(
    {
      id: "features-fill",
      type: "fill",
      source: SOURCES.features,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": "#90AE9B", "fill-opacity": 0.2 },
    },
    "entity-clusters",
  );
  map.addLayer(
    {
      id: "features-line",
      type: "line",
      source: SOURCES.features,
      filter: [
        "any",
        ["==", ["geometry-type"], "Polygon"],
        ["==", ["geometry-type"], "LineString"],
      ],
      paint: {
        "line-color": "#52735E",
        "line-width": 2,
        "line-dasharray": [2, 1],
      },
    },
    "entity-clusters",
  );
  map.addLayer(
    {
      id: "features-label",
      type: "symbol",
      source: SOURCES.features,
      layout: {
        "text-field": ["get", "name"],
        "text-size": 11,
        "text-font": FONT,
        "symbol-placement": "point",
      },
      paint: {
        "text-color": "#52735E",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1,
      },
    },
    "entity-clusters",
  );
}

export function setFeatures(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): void {
  const source = map.getSource(SOURCES.features) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}

export interface EventFeatureProperties {
  event_id: string;
  event_type: string;
  severity: string;
  title: string;
  time: string;
  entity_id: string | null;
  alert_id: string | null;
  alert_status: string | null;
  icon_key: string;
}

/** Recent events use the event marker family (diamond), so a wolf detection never looks like a
 * tracked wolf (architecture 24.5). Placed under the entity layers so entities stay on top.
 * Clicks are bound with `bindEventClicks`, for the reason given at `ensureEntityLayers`. */
export function ensureEventLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.events)) return;
  map.addSource(SOURCES.events, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    promoteId: "event_id",
  });
  map.addLayer(
    {
      id: "event-markers",
      type: "symbol",
      source: SOURCES.events,
      layout: {
        "icon-image": ["get", "marker"],
        "icon-size": 0.7,
        "icon-allow-overlap": true,
      },
      paint: { "icon-opacity": 0.95 },
    },
    "entity-clusters",
  );
  map.on(
    "mouseenter",
    "event-markers",
    () => (map.getCanvas().style.cursor = "pointer"),
  );
  map.on(
    "mouseleave",
    "event-markers",
    () => (map.getCanvas().style.cursor = ""),
  );
}

/** Bind the event marker click; the returned function unbinds it. */
export function bindEventClicks(
  map: MapLibreMap,
  onClick: (props: EventFeatureProperties) => void,
): () => void {
  const onMarker = (e: MapLayerMouseEvent) => {
    const feature = e.features?.[0];
    if (feature)
      onClick(feature.properties as unknown as EventFeatureProperties);
  };
  map.on("click", "event-markers", onMarker);
  return () => map.off("click", "event-markers", onMarker);
}

export async function setEvents(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): Promise<void> {
  const source = map.getSource(SOURCES.events) as GeoJSONSource | undefined;
  if (!source) return;
  const withMarkers: GeoJSON.Feature[] = [];
  for (const feature of features) {
    const props = feature.properties as unknown as EventFeatureProperties;
    const state: MarkerState =
      props.alert_status === "open"
        ? "critical"
        : props.severity === "warning"
          ? "warning"
          : "normal";
    const marker = await ensureMarkerImage(map, props.icon_key, state);
    withMarkers.push({
      ...feature,
      properties: { ...feature.properties, marker },
    });
  }
  source.setData({ type: "FeatureCollection", features: withMarkers });
}

export interface GatewayFeatureProperties {
  gateway_id: string;
  name: string;
  last_seen_at: string | null;
}

/** Gateways as small squares under the entities: the network, not the animals. The coverage
 * analysis of decision D107 will draw on the same source later. */
export function ensureGatewayLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.gateways)) return;
  map.addSource(SOURCES.gateways, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    promoteId: "gateway_id",
  });
  map.addLayer(
    {
      id: "gateway-markers",
      type: "circle",
      source: SOURCES.gateways,
      paint: {
        "circle-radius": 6,
        "circle-color": "#2F4A3A",
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
        "circle-opacity": 0.9,
      },
    },
    "entity-clusters",
  );
  map.addLayer(
    {
      id: "gateway-labels",
      type: "symbol",
      source: SOURCES.gateways,
      minzoom: 9,
      layout: {
        "text-field": ["get", "name"],
        "text-size": 10,
        "text-font": FONT,
        "text-offset": [0, 1.2],
        "text-anchor": "top",
        "text-optional": true,
      },
      paint: {
        "text-color": "#2F4A3A",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1,
      },
    },
    "entity-clusters",
  );
}

export function setGateways(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): void {
  const source = map.getSource(SOURCES.gateways) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}

/** Signal colour: red at -120 dBm, amber around -105, green from -80 (a ttnmapper-like scale). */
const RSSI_COLOR: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["coalesce", ["get", "best_rssi"], -125],
  -125,
  "#b91c1c",
  -110,
  "#f59e0b",
  -95,
  "#a3c14a",
  -80,
  "#15803d",
];

/** Where collars were heard (decision D107): hexagons with the count and best signal when zoomed
 * out, the heard positions themselves when zoomed in. Under the gateways and entities. */
export function ensureCoverageLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.coverage)) return;
  map.addSource(SOURCES.coverage, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  const before = map.getLayer("gateway-markers")
    ? "gateway-markers"
    : "entity-clusters";
  map.addLayer(
    {
      id: "coverage-hex",
      type: "fill",
      source: SOURCES.coverage,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": RSSI_COLOR, "fill-opacity": 0.45 },
    },
    before,
  );
  map.addLayer(
    {
      id: "coverage-hex-line",
      type: "line",
      source: SOURCES.coverage,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: {
        "line-color": "#ffffff",
        "line-width": 0.5,
        "line-opacity": 0.6,
      },
    },
    before,
  );
  map.addLayer(
    {
      id: "coverage-points",
      type: "circle",
      source: SOURCES.coverage,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 4,
        "circle-color": RSSI_COLOR,
        "circle-opacity": 0.85,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 0.5,
      },
    },
    before,
  );
}

export function setCoverage(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): void {
  const source = map.getSource(SOURCES.coverage) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}
