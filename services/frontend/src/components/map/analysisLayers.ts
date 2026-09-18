import type {
  ExpressionSpecification,
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
export const INTENSITY_SOURCE = "analysis-intensity";
/** The share of the busiest cell each colour of the use intensity starts at. */
export const INTENSITY_STEPS = [0, 0.05, 0.2, 0.4, 0.7] as const;
export const VEGETATION_SOURCE = "analysis-vegetation";
/** Light to dark, by the share of the busiest cell: the sequential ramp of a use map.
 *
 * Warm, not green (Tim, 2026-09-18). Green belongs to the vegetation layer, where bare to green
 * is what everyone already reads a satellite index as, and two green ramps over one another
 * cannot be told apart. Of the candidates measured against the vegetation ramp, warm separates
 * best under both red-green colour blindnesses (it differs in brightness and in its blue
 * content, not along the red-green axis where those two ramps would collide) and stays furthest
 * from the blue the base maps paint water with, which is what rules a blue ramp out. It also
 * says the right thing: warm is how hard the ground was used, green is what it grows. */
export const INTENSITY_RAMP = [
  "#FDF0E3",
  "#F8D6B0",
  "#EFB173",
  "#DC8A3C",
  "#B0621B",
] as const;
export const ANALYSIS_KINDS = [
  "area",
  "mcp",
  "kde",
  "hotspot",
  "cluster",
  "coverage",
  "gateway",
] as const;
export type AnalysisKind = (typeof ANALYSIS_KINDS)[number];

const FILL_OPACITY: Record<string, number> = {
  area: 0.35,
  mcp: 0.08,
  kde: 0.22,
  hotspot: 0.45,
  cluster: 0.18,
  coverage: 0.1,
};

/** The colour of a fix by its accuracy: under 10 m, under 30 m, under 100 m, worse, unknown
 * (the device performance map, decision D220). */
export const ACCURACY_CLASSES: [number, string][] = [
  [10, "#3E6B4E"],
  [30, "#9DBFA8"],
  [100, "#D9A441"],
  [Infinity, "#B86B5C"],
];
export const ACCURACY_UNKNOWN = "#9CA3AF";

export function accuracyColor(accuracy: number | null | undefined): string {
  if (accuracy === null || accuracy === undefined) return ACCURACY_UNKNOWN;
  for (const [bound, color] of ACCURACY_CLASSES)
    if (accuracy < bound) return color;
  return ACCURACY_UNKNOWN;
}

/** A five-step ramp for an area's relative grazing pressure: 1.0 is the herd's average over the
 * chosen areas. Null (no use anywhere) is the lightest step.
 *
 * Warm like the use intensity it summarises, since both say how hard the ground was worked and
 * green is the vegetation layer's (Tim, 2026-09-18). It ran green to coral before, which was not
 * only a second green: coral is lighter than the dark green under it, so "twice the average"
 * came out paler than "above average" and the ramp reversed at its most important step. */
export const PRESSURE_RAMP = [
  "#F6F0EA",
  "#E6D6C6",
  "#D2B096",
  "#BE8663",
  "#AF4436",
] as const;

/** Bare to green for the vegetation index of an area (Tim, 2026-09-18), a sequential ramp
 * apart from the pressure one so the two layers never read as the same thing. `level` is the
 * index scaled to 0 to 1 by the module. */
/** The five colours divide the cells into fifths by rank, so each starts a fifth of the way up. */
export const VEGETATION_STEPS = [0, 0.2, 0.4, 0.6, 0.8] as const;

export const VEGETATION_RAMP = [
  "#D9C8A6",
  "#BFC78F",
  "#94B277",
  "#5F9455",
  "#2F6B3A",
] as const;

export function pressureColor(level: number | null | undefined): string {
  if (level === null || level === undefined || !Number.isFinite(level))
    return PRESSURE_RAMP[0];
  if (level < 0.25) return PRESSURE_RAMP[0];
  if (level < 0.75) return PRESSURE_RAMP[1];
  if (level < 1.25) return PRESSURE_RAMP[2];
  if (level < 2) return PRESSURE_RAMP[3];
  return PRESSURE_RAMP[4];
}

/** The features with their colour and opacity set, ordered so the largest draw first: the
 * areas under everything, the 95 percent isopleth under the 50, the hull under the rest of
 * its subject. An area is coloured by its pressure, everything else by its subject. */
export function decorateAnalysisFeatures(
  features: GeoJSON.Feature[],
  colorOf: (subjectId: string | null) => string,
): GeoJSON.Feature[] {
  const rank = (f: GeoJSON.Feature): number => {
    const kind = String(f.properties?.kind ?? "");
    const level = Number(f.properties?.level ?? 0);
    if (kind === "area") return -1;
    if (kind === "coverage") return -0.5;
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
      const level = f.properties?.level as number | null | undefined;
      return {
        ...f,
        properties: {
          ...f.properties,
          color: kind === "area" ? pressureColor(level) : colorOf(subject),
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
  // the gateways heard (device performance): a point sized by its share of the uplinks, and
  // where a pair met (contact tracing): a point sized by how often, since the question a map
  // answers that a table cannot is *where* animals meet, and the answer is usually one place
  map.addLayer({
    id: "analysis-points",
    type: "circle",
    source: ANALYSIS_SOURCE,
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": [
        "case",
        ["==", ["get", "kind"], "contact"],
        [
          "interpolate",
          ["linear"],
          ["coalesce", ["get", "contacts"], 1],
          1,
          5,
          50,
          18,
        ],
        ["+", 5, ["*", 12, ["coalesce", ["get", "level"], 0]]],
      ],
      "circle-color": ["coalesce", ["get", "color"], "#52735E"],
      "circle-opacity": 0.85,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
    },
  });
}

/** The fixes of a device coloured by their accuracy class (device performance). */
export const FIXES_SOURCE = "analysis-fixes";

export function ensureFixLayer(map: MapLibreMap): void {
  if (map.getSource(FIXES_SOURCE)) return;
  map.addSource(FIXES_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: "analysis-fixes",
    type: "circle",
    source: FIXES_SOURCE,
    paint: {
      "circle-radius": 3.5,
      "circle-color": ["coalesce", ["get", "color"], ACCURACY_UNKNOWN],
      "circle-opacity": 0.9,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.5,
    },
  });
}

export function setFixFeatures(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): void {
  const source = map.getSource(FIXES_SOURCE) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}

export function setFixesVisible(map: MapLibreMap, visible: boolean): void {
  if (map.getLayer("analysis-fixes"))
    map.setLayoutProperty(
      "analysis-fixes",
      "visibility",
      visible ? "visible" : "none",
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
  if (map.getLayer("analysis-points"))
    map.setFilter("analysis-points", [
      "all",
      ["==", ["geometry-type"], "Point"],
      filter,
    ]);
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
  // the vegetation mosaic answers too, so a cell can be read (Tim, 2026-09-18)
  const layers = ["analysis-fill", "analysis-points", "vegetation-fill"];
  for (const id of layers) {
    map.on("click", id, onClick);
    map.on("mouseenter", id, enter);
    map.on("mouseleave", id, leave);
  }
  return () => {
    for (const id of layers) {
      map.off("click", id, onClick);
      map.off("mouseenter", id, enter);
      map.off("mouseleave", id, leave);
    }
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
    if (f.geometry && "coordinates" in f.geometry)
      visit(f.geometry.coordinates);
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

/** The use intensity cells (grazing) under the analysis polygons: a choropleth of hours per
 * cell, the darker the more. */
/** A MapLibre `step` expression from a ramp and the value each colour starts at. The first
 * colour is the floor, so the thresholds after it are what the expression names. */
function rampExpression(
  property: string,
  ramp: readonly string[],
  steps: readonly number[],
): ExpressionSpecification {
  const out: unknown[] = ["step", ["get", property], ramp[0]];
  for (let i = 1; i < ramp.length; i++) out.push(steps[i], ramp[i]);
  return out as ExpressionSpecification;
}

export function ensureIntensityLayers(map: MapLibreMap): void {
  if (map.getSource(INTENSITY_SOURCE)) return;
  map.addSource(INTENSITY_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  const before = map.getLayer("analysis-fill")
    ? "analysis-fill"
    : map.getLayer("track-line")
      ? "track-line"
      : undefined;
  map.addLayer(
    {
      id: "intensity-fill",
      type: "fill",
      source: INTENSITY_SOURCE,
      paint: {
        // the thresholds live beside the ramp, so the layer and its legend cannot drift apart
        "fill-color": rampExpression("share", INTENSITY_RAMP, INTENSITY_STEPS),
        "fill-opacity": 0.8,
      },
    },
    before,
  );
}

export function setIntensityFeatures(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): void {
  const source = map.getSource(INTENSITY_SOURCE) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}

/** The vegetation mosaic (grazing): the index per cell on the same grid as the use intensity,
 * so the two can be read against each other. Its own source, so either can be shown alone. */
export function ensureVegetationLayers(map: MapLibreMap): void {
  if (map.getSource(VEGETATION_SOURCE)) return;
  map.addSource(VEGETATION_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  const before = map.getLayer("intensity-fill")
    ? "intensity-fill"
    : map.getLayer("analysis-fill")
      ? "analysis-fill"
      : undefined;
  map.addLayer(
    {
      id: "vegetation-fill",
      type: "fill",
      source: VEGETATION_SOURCE,
      paint: {
        "fill-color": rampExpression(
          "level",
          VEGETATION_RAMP,
          VEGETATION_STEPS,
        ),
        "fill-opacity": 0.8,
      },
    },
    before,
  );
}

export function setVegetationFeatures(
  map: MapLibreMap,
  features: GeoJSON.Feature[],
): void {
  const source = map.getSource(VEGETATION_SOURCE) as GeoJSONSource | undefined;
  source?.setData({ type: "FeatureCollection", features });
}

export function setVegetationVisible(map: MapLibreMap, visible: boolean): void {
  if (map.getLayer("vegetation-fill"))
    map.setLayoutProperty(
      "vegetation-fill",
      "visibility",
      visible ? "visible" : "none",
    );
}

export function setIntensityVisible(map: MapLibreMap, visible: boolean): void {
  if (map.getLayer("intensity-fill"))
    map.setLayoutProperty(
      "intensity-fill",
      "visibility",
      visible ? "visible" : "none",
    );
}

export function setTracksVisible(map: MapLibreMap, visible: boolean): void {
  for (const id of ["track-line", "track-line-device"]) {
    if (map.getLayer(id))
      map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}
