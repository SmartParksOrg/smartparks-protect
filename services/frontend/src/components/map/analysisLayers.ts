import type {
  FilterSpecification,
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from "maplibre-gl";

import { SOURCES } from "@/components/map/layers";

/**
 * The result polygons of an analysis on a map (docs/ANALYTICS_PHASE1_PLAN.md, section 8.5):
 * home range hulls and isopleths, hotspot cells and cluster hulls, each in its subject's
 * colour, translucent, the larger ones drawn first. The page toggles kinds; a click reports
 * the polygon's properties.
 */
export const ANALYSIS_SOURCE = "analysis";
export const ANALYSIS_KINDS = ["mcp", "kde", "hotspot", "cluster"] as const;
export type AnalysisKind = (typeof ANALYSIS_KINDS)[number];

const FILL_OPACITY: Record<string, number> = {
  mcp: 0.08,
  kde: 0.22,
  hotspot: 0.45,
  cluster: 0.18,
};

/** The features with their colour and opacity set, ordered so the largest draw first: the
 * 95 percent isopleth under the 50, the hull under everything of its subject. */
export function decorateAnalysisFeatures(
  features: GeoJSON.Feature[],
  colorOf: (subjectId: string | null) => string,
): GeoJSON.Feature[] {
  const rank = (f: GeoJSON.Feature): number => {
    const kind = String(f.properties?.kind ?? "");
    const level = Number(f.properties?.level ?? 0);
    if (kind === "mcp") return 0;
    if (kind === "kde") return level >= 0.9 ? 1 : 2;
    if (kind === "cluster") return 3;
    return 4;
  };
  return [...features]
    .sort((a, b) => rank(a) - rank(b))
    .map((f) => {
      const kind = String(f.properties?.kind ?? "");
      const subject = (f.properties?.subject_id as string | null) ?? null;
      return {
        ...f,
        properties: {
          ...f.properties,
          color: colorOf(subject),
          opacity: FILL_OPACITY[kind] ?? 0.2,
        },
      };
    });
}

export function ensureAnalysisLayers(map: MapLibreMap): void {
  if (map.getSource(ANALYSIS_SOURCE)) return;
  map.addSource(ANALYSIS_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  // under the tracks when they exist, so the path stays readable over the polygons
  const before = map.getLayer("track-line")
    ? "track-line"
    : map.getLayer("entity-clusters")
      ? "entity-clusters"
      : undefined;
  map.addLayer(
    {
      id: "analysis-fill",
      type: "fill",
      source: ANALYSIS_SOURCE,
      paint: {
        "fill-color": ["coalesce", ["get", "color"], "#52735E"],
        "fill-opacity": ["coalesce", ["get", "opacity"], 0.2],
      },
    },
    before,
  );
  map.addLayer(
    {
      id: "analysis-line",
      type: "line",
      source: ANALYSIS_SOURCE,
      paint: {
        "line-color": ["coalesce", ["get", "color"], "#52735E"],
        "line-width": ["match", ["get", "kind"], "hotspot", 0.5, 1.5],
        "line-opacity": 0.9,
      },
    },
    before,
  );
}

export function setAnalysisFeatures(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): void {
  const source = map.getSource(ANALYSIS_SOURCE) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}

/** Show only these kinds; an empty list hides every polygon. */
export function setAnalysisKinds(map: MapLibreMap, kinds: string[]): void {
  const filter: FilterSpecification = [
    "in",
    ["get", "kind"],
    ["literal", kinds],
  ];
  for (const id of ["analysis-fill", "analysis-line"]) {
    if (map.getLayer(id)) map.setFilter(id, filter);
  }
}

/** A click on a polygon reports its properties; returns the unbind. */
export function bindAnalysisClicks(
  map: MapLibreMap,
  onPick: (properties: Record<string, unknown>) => void,
): () => void {
  const onClick = (e: MapLayerMouseEvent) => {
    const props = e.features?.[0]?.properties;
    if (props) onPick(props as Record<string, unknown>);
  };
  const enter = () => {
    map.getCanvas().style.cursor = "pointer";
  };
  const leave = () => {
    map.getCanvas().style.cursor = "";
  };
  map.on("click", "analysis-fill", onClick);
  map.on("mouseenter", "analysis-fill", enter);
  map.on("mouseleave", "analysis-fill", leave);
  return () => {
    map.off("click", "analysis-fill", onClick);
    map.off("mouseenter", "analysis-fill", enter);
    map.off("mouseleave", "analysis-fill", leave);
  };
}

/** The bounding box of the features, `[[west, south], [east, north]]`, or null. */
export function boundsOfFeatures(
  features: GeoJSON.Feature[],
): [[number, number], [number, number]] | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  const visit = (coordinates: unknown): void => {
    if (!Array.isArray(coordinates)) return;
    if (typeof coordinates[0] === "number") {
      const [x, y] = coordinates as number[];
      west = Math.min(west, x);
      east = Math.max(east, x);
      south = Math.min(south, y);
      north = Math.max(north, y);
      return;
    }
    for (const c of coordinates) visit(c);
  };
  for (const f of features) {
    if (f.geometry && "coordinates" in f.geometry) visit(f.geometry.coordinates);
  }
  return Number.isFinite(west)
    ? [
        [west, south],
        [east, north],
      ]
    : null;
}

/** Keep the source ids apart: the analysis source is not one of the live map's. */
export const _sourcesOfTheLiveMap = SOURCES;
