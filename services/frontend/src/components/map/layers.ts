import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

import { ensureMarkerImage, type MarkerState } from "@/components/icons/markers";

export const SOURCES = { entities: "entities", track: "track", features: "features" } as const;

/** Glyphs the OpenFreeMap styles serve; the MapLibre default (Open Sans) is not among them. */
const FONT = ["Noto Sans Regular"];

export interface EntityFeatureProperties {
  entity_id: string;
  name: string;
  status: string;
  entity_type: string;
  group: string;
  icon_key: string;
  device_id: string | null;
  last_seen_at: string | null;
  position_time: string | null;
  active_alert_count: number;
}

const OFFLINE_AFTER_MS = 24 * 3600_000;

export function stateFor(props: EntityFeatureProperties, selectedId: string | null): MarkerState {
  if (props.entity_id === selectedId) return "selected";
  if (props.active_alert_count > 0) return "critical";
  if (props.last_seen_at && Date.now() - new Date(props.last_seen_at).getTime() > OFFLINE_AFTER_MS) return "offline";
  return "normal";
}

/** Add the entity source and layers once; features are pushed with `setEntities`. */
export function ensureEntityLayers(map: MapLibreMap, onClick: (props: EntityFeatureProperties) => void, onClusterClick: (lngLat: [number, number], clusterId: number) => void): void {
  if (map.getSource(SOURCES.entities)) return;
  map.addSource(SOURCES.entities, { type: "geojson", data: { type: "FeatureCollection", features: [] }, cluster: true, clusterRadius: 48, clusterMaxZoom: 14, promoteId: "entity_id" });
  map.addLayer({ id: "entity-clusters", type: "circle", source: SOURCES.entities, filter: ["has", "point_count"], paint: { "circle-color": "#52735E", "circle-radius": ["step", ["get", "point_count"], 16, 10, 20, 50, 26], "circle-stroke-width": 3, "circle-stroke-color": "#ffffff" } });
  map.addLayer({ id: "entity-cluster-count", type: "symbol", source: SOURCES.entities, filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12, "text-font": FONT }, paint: { "text-color": "#ffffff" } });
  map.addLayer({
    id: "entity-markers",
    type: "symbol",
    source: SOURCES.entities,
    filter: ["!", ["has", "point_count"]],
    layout: { "icon-image": ["get", "marker"], "icon-size": 0.9, "icon-allow-overlap": true, "text-field": ["get", "name"], "text-size": 11, "text-font": FONT, "text-offset": [0, 1.8], "text-anchor": "top", "text-optional": true },
    paint: { "text-color": "#1f2a24", "text-halo-color": "#ffffff", "text-halo-width": 1.2 },
  });
  map.on("click", "entity-markers", (e) => {
    const feature = e.features?.[0];
    if (feature) onClick(feature.properties as unknown as EntityFeatureProperties);
  });
  map.on("click", "entity-clusters", (e) => {
    const feature = e.features?.[0];
    if (!feature) return;
    const geometry = feature.geometry as GeoJSON.Point;
    onClusterClick(geometry.coordinates as [number, number], feature.properties?.cluster_id as number);
  });
  for (const layer of ["entity-markers", "entity-clusters"]) {
    map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }
}

export async function setEntities(map: MapLibreMap, features: GeoJSON.Feature[], selectedId: string | null): Promise<void> {
  const source = map.getSource(SOURCES.entities) as GeoJSONSource | undefined;
  if (!source) return;
  const withMarkers: GeoJSON.Feature[] = [];
  for (const feature of features) {
    const props = feature.properties as unknown as EntityFeatureProperties;
    const state = stateFor(props, selectedId);
    const marker = await ensureMarkerImage(map, props.icon_key, state);
    withMarkers.push({ ...feature, properties: { ...feature.properties, marker } });
  }
  source.setData({ type: "FeatureCollection", features: withMarkers });
}

export function ensureTrackLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.track)) return;
  map.addSource(SOURCES.track, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "track-line", type: "line", source: SOURCES.track, filter: ["==", ["geometry-type"], "LineString"], paint: { "line-color": "#2F4A3A", "line-width": 3, "line-opacity": 0.85 } }, "entity-clusters");
  map.addLayer({ id: "track-points", type: "circle", source: SOURCES.track, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 3, "circle-color": "#ffffff", "circle-stroke-color": "#2F4A3A", "circle-stroke-width": 1.5 } }, "entity-clusters");
}

export function setTrack(map: MapLibreMap, geometry: GeoJSON.Geometry | null, times: string[]): void {
  const source = map.getSource(SOURCES.track) as GeoJSONSource | undefined;
  if (!source) return;
  if (!geometry) {
    source.setData({ type: "FeatureCollection", features: [] });
    return;
  }
  const features: GeoJSON.Feature[] = [{ type: "Feature", geometry, properties: {} }];
  const coordinates = geometry.type === "LineString" ? geometry.coordinates : geometry.type === "MultiPoint" ? geometry.coordinates : [];
  coordinates.forEach((c, i) => features.push({ type: "Feature", geometry: { type: "Point", coordinates: c }, properties: { time: times[i] } }));
  source.setData({ type: "FeatureCollection", features });
}

export function ensureFeatureLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCES.features)) return;
  map.addSource(SOURCES.features, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "features-fill", type: "fill", source: SOURCES.features, filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#90AE9B", "fill-opacity": 0.2 } }, "entity-clusters");
  map.addLayer({ id: "features-line", type: "line", source: SOURCES.features, filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "LineString"]], paint: { "line-color": "#52735E", "line-width": 2, "line-dasharray": [2, 1] } }, "entity-clusters");
  map.addLayer({ id: "features-label", type: "symbol", source: SOURCES.features, layout: { "text-field": ["get", "name"], "text-size": 11, "text-font": FONT, "symbol-placement": "point" }, paint: { "text-color": "#52735E", "text-halo-color": "#ffffff", "text-halo-width": 1 } }, "entity-clusters");
}

export function setFeatures(map: MapLibreMap, features: GeoJSON.Feature[]): void {
  const source = map.getSource(SOURCES.features) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}
