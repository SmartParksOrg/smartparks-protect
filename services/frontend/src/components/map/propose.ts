import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

/**
 * Areas proposed from a click (phase 33, decision D270) or from a name (D273): the candidates
 * the API answers and the faint outlines a map draws for them while a person chooses. The
 * chosen one goes into the drawing session, where it is edited like any drawn polygon.
 */
export interface ProposedArea {
  kind: "enclosed" | "osm" | string;
  name: string;
  geometry: GeoJSON.Geometry;
  area_m2: number;
  clipped: boolean;
  osm_id?: number | null;
  tags?: Record<string, string>;
  /** The name is the area's own, not its kind in words. */
  named?: boolean;
}

export interface ProposedAreas {
  candidates: ProposedArea[];
  attribution: string;
  /** A search whose view was too wide read only its middle (decision D273). */
  narrowed?: boolean;
}

const SOURCE = "propose-ghosts";
const LAYERS = ["propose-ghost-fill", "propose-ghost-line"];

/** The outlines' source and layers, once per map. */
export function ensureGhostLayers(map: MapLibreMap): void {
  if (map.getSource(SOURCE)) return;
  map.addSource(SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: "propose-ghost-fill",
    type: "fill",
    source: SOURCE,
    paint: { "fill-color": "#C6B187", "fill-opacity": 0.18 },
  });
  map.addLayer({
    id: "propose-ghost-line",
    type: "line",
    source: SOURCE,
    paint: {
      "line-color": "#C6B187",
      "line-width": 2,
      "line-dasharray": [2, 2],
    },
  });
}

/** The outlines shown: every candidate, the one under the pointer stronger. */
export function setGhosts(map: MapLibreMap, candidates: ProposedArea[]): void {
  const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
  if (!source) return;
  source.setData({
    type: "FeatureCollection",
    features: candidates.map((c, index) => ({
      type: "Feature",
      geometry: c.geometry,
      properties: { index, name: c.name },
    })),
  });
}

export function removeGhostLayers(map: MapLibreMap): void {
  for (const id of LAYERS) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
}

/** The kind of a candidate in words: what OpenStreetMap calls it, or the enclosure. */
export function candidateKind(candidate: ProposedArea): string {
  const kind = candidate.tags?.kind;
  if (!kind) return candidate.kind;
  const [key, value] = kind.split("=");
  return value ? `${value.replace(/_/g, " ")} (${key})` : kind;
}

/** What the drawing editor would have to hold: how many pieces the shape is in and how many
 * enclaves it has inside it. terra-draw keeps one polygon of one ring at a time (phase 33,
 * decision D274), so a zone made of several reserves, or one with an enclave, is kept as it
 * came instead of being loaded into the editor and silently dropped. */
export function shapeParts(geometry: GeoJSON.Geometry): {
  parts: number;
  holes: number;
} {
  if (geometry.type === "Polygon")
    return { parts: 1, holes: Math.max(geometry.coordinates.length - 1, 0) };
  if (geometry.type === "MultiPolygon")
    return {
      parts: geometry.coordinates.length,
      holes: geometry.coordinates.reduce(
        (n, part) => n + Math.max(part.length - 1, 0),
        0,
      ),
    };
  return { parts: 1, holes: 0 };
}

/** Whether the drawing editor can take the shape and give it back unchanged. */
export function heldByEditor(geometry: GeoJSON.Geometry): boolean {
  const { parts, holes } = shapeParts(geometry);
  return geometry.type === "Polygon" && parts === 1 && holes === 0;
}
