import type { AnalysisRun, EntityGroup, Feature } from "@/api/types";
import { PALETTE } from "@/lib/chartStyle";
import type { ExportPreset } from "@/lib/exports";

/** The analysis pages' shared pieces (docs/ANALYTICS_PHASE1_PLAN.md, sections 8 and 9): the
 * result document as the frontend reads it, the run states, and the form state in the URL. */

export interface ResultSubject {
  id: string;
  name: string;
  type?: string | null;
}
export interface ResultPeriod {
  key: "main" | "comparison";
  time_from: string;
  time_to: string;
}
export interface ResultWarning {
  code: string;
  level: "notice" | "warning";
  subject_id?: string | null;
  text: string;
}
export interface ResultTable {
  key: string;
  columns: string[];
  rows: unknown[][];
}
export interface ResultChartSeries {
  subject?: string;
  period?: string;
  name?: string;
  /** Grazing: the area the series belongs to, and the herd when two are compared. */
  area?: string;
  herd?: string;
  data: [number | string, number | null][];
}
export interface ResultChart {
  key: string;
  kind: "line" | "bar" | "rose" | "stacked";
  unit?: string | null;
  series: ResultChartSeries[];
}
export interface ResultDocument {
  version: number;
  module: string;
  method_version: string;
  subjects: ResultSubject[];
  periods: ResultPeriod[];
  summary: Record<string, unknown>;
  tables: ResultTable[];
  charts: ResultChart[];
  geometries: Record<string, number>;
  warnings: ResultWarning[];
  provenance: Record<string, unknown>;
}

export const ACTIVE_STATES = new Set(["queued", "running"]);
export const isActive = (status: string): boolean => ACTIVE_STATES.has(status);

/** The result document of a run, when it has one and it is the version this code reads. */
export function documentOf(
  run: AnalysisRun | undefined,
): ResultDocument | null {
  const doc = run?.result as ResultDocument | null | undefined;
  if (!doc || doc.version !== 1) return null;
  return doc;
}

/** The method options of the movement module (plan, section 8.1), as the URL carries them. */
export interface MethodOptions {
  /** Hours; an interval longer than this is a gap, not movement. */
  gap: number;
  /** Metres per second; a fix implying more is left out. */
  speed_max: number;
  /** Metres; the grid cell for residence and hotspots, and the cluster distance. */
  cell: number;
  methods: string[];
  /** Metres, or null for the reference bandwidth. */
  kde_bandwidth: number | null;
}

export const ALL_METHODS = ["mcp", "kde", "clusters"];
export const DEFAULT_METHOD: MethodOptions = {
  gap: 4,
  speed_max: 15,
  cell: 100,
  methods: ALL_METHODS,
  kde_bandwidth: null,
};

/** The grazing page's own choices (plan, section 9.4): the areas, the weighting, the second
 * herd, and the visit and rest options. */
export interface GrazingOptions {
  areas: string[];
  weighting: "equal" | "attribute" | "metabolic";
  weight_key: string | null;
  /** The group of the second herd; its members become `herd_b_entity_ids`. */
  herd_b: string | null;
  seasons: boolean;
  /** Hours away from an area before a new visit. */
  absence: number;
  /** Animal-hours at or below which a day counts as rest. */
  rest: number;
}

export const DEFAULT_GRAZING: GrazingOptions = {
  areas: [],
  weighting: "equal",
  weight_key: null,
  herd_b: null,
  seasons: false,
  absence: 6,
  rest: 0,
};

/** The subjects and the period as the pages keep them in the URL. */
export interface FormState {
  entities: string[];
  group: string | null;
  type: string | null;
  range: string;
  from: string | null;
  to: string | null;
  compare: string | null;
  run: string | null;
  method: MethodOptions;
  grazing: GrazingOptions;
}

export const DEFAULT_RANGE = "30d";

function numberOr(value: string | null, fallback: number): number {
  const n = value === null ? NaN : Number(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export function readFormState(params: URLSearchParams): FormState {
  const methods = params.get("methods");
  return {
    entities: params.getAll("entity"),
    group: params.get("group"),
    type: params.get("type"),
    range: params.get("range") ?? DEFAULT_RANGE,
    from: params.get("from"),
    to: params.get("to"),
    compare: params.get("compare"),
    run: params.get("run"),
    method: {
      gap: numberOr(params.get("gap"), DEFAULT_METHOD.gap),
      speed_max: numberOr(params.get("speed_max"), DEFAULT_METHOD.speed_max),
      cell: numberOr(params.get("cell"), DEFAULT_METHOD.cell),
      methods:
        methods === null
          ? ALL_METHODS
          : methods.split(",").filter((m) => ALL_METHODS.includes(m)),
      kde_bandwidth: params.get("kde")
        ? numberOr(params.get("kde"), 0) || null
        : null,
    },
    grazing: {
      areas: params.getAll("area"),
      weighting: (["equal", "attribute", "metabolic"] as const).includes(
        params.get("weighting") as "equal",
      )
        ? (params.get("weighting") as GrazingOptions["weighting"])
        : "equal",
      weight_key: params.get("weight_key"),
      herd_b: params.get("herd_b"),
      seasons: params.get("seasons") === "1",
      absence: numberOr(params.get("absence"), DEFAULT_GRAZING.absence),
      rest: params.get("rest") === null ? 0 : numberOr(params.get("rest"), 0),
    },
  };
}

export function writeFormState(state: FormState): URLSearchParams {
  const params = new URLSearchParams();
  for (const id of state.entities) params.append("entity", id);
  if (state.group) params.set("group", state.group);
  if (state.type) params.set("type", state.type);
  if (state.range !== DEFAULT_RANGE) params.set("range", state.range);
  if (state.range === "custom") {
    if (state.from) params.set("from", state.from);
    if (state.to) params.set("to", state.to);
  }
  if (state.compare) params.set("compare", state.compare);
  const m = state.method;
  if (m.gap !== DEFAULT_METHOD.gap) params.set("gap", String(m.gap));
  if (m.speed_max !== DEFAULT_METHOD.speed_max)
    params.set("speed_max", String(m.speed_max));
  if (m.cell !== DEFAULT_METHOD.cell) params.set("cell", String(m.cell));
  if (m.methods.join(",") !== ALL_METHODS.join(","))
    params.set("methods", m.methods.join(","));
  if (m.kde_bandwidth) params.set("kde", String(m.kde_bandwidth));
  const g = state.grazing;
  for (const id of g.areas) params.append("area", id);
  if (g.weighting !== "equal") params.set("weighting", g.weighting);
  if (g.weight_key) params.set("weight_key", g.weight_key);
  if (g.herd_b) params.set("herd_b", g.herd_b);
  if (g.seasons) params.set("seasons", "1");
  if (g.absence !== DEFAULT_GRAZING.absence)
    params.set("absence", String(g.absence));
  if (g.rest) params.set("rest", String(g.rest));
  if (state.run) params.set("run", state.run);
  return params;
}

/** The parameters the grazing module takes; null until subjects and areas are chosen. The
 * second herd's members come from the caller, who knows the entities of the group. */
export function grazingParameters(
  state: FormState,
  herdB: string[],
  now: Date = new Date(),
): Record<string, unknown> | null {
  const window = windowOf(state, now);
  if (
    !window ||
    state.entities.length === 0 ||
    state.grazing.areas.length === 0
  )
    return null;
  const comparison = comparisonOf(state, window);
  const g = state.grazing;
  return {
    entity_ids: state.entities,
    ...window,
    ...(comparison ? { comparison } : {}),
    feature_ids: g.areas,
    weighting: g.weighting,
    ...(g.weighting !== "equal" && g.weight_key
      ? { weight_key: g.weight_key }
      : {}),
    seasons: g.seasons,
    ...(herdB.length ? { herd_b_entity_ids: herdB } : {}),
    gap_hours: state.method.gap,
    min_absence_hours: g.absence,
    cell_m: state.method.cell,
    rest_threshold_hours: g.rest,
    max_speed_mps: state.method.speed_max,
  };
}

/** The parameters the movement module takes, from the form; null while the form is not
 * complete (no subjects, or a custom range without both dates). */
export function movementParameters(
  state: FormState,
  now: Date = new Date(),
): Record<string, unknown> | null {
  const window = windowOf(state, now);
  if (!window || state.entities.length === 0) return null;
  const comparison = comparisonOf(state, window);
  const m = state.method;
  return {
    entity_ids: state.entities,
    ...window,
    ...(comparison ? { comparison } : {}),
    gap_hours: m.gap,
    max_speed_mps: m.speed_max,
    cell_m: m.cell,
    methods: m.methods,
    ...(m.kde_bandwidth ? { kde_bandwidth_m: m.kde_bandwidth } : {}),
  };
}

/** One brand colour per subject of a result, in the document's order, used alike on the
 * cards, the charts, the polygons and the track, so one animal has one colour everywhere. */
export function subjectPalette(
  document: ResultDocument,
): Record<string, string> {
  return Object.fromEntries(
    document.subjects.map((s, i) => [s.id, PALETTE[i % PALETTE.length]]),
  );
}

/** The per-subject figures of a period from a movement or grazing summary shaped
 * `{period: {subject: {metric: value}}}`, or null when the summary is flat. */
export function subjectSummary(
  document: ResultDocument,
  period: string,
  subjectId: string,
): Record<string, number | null> | null {
  const block = document.summary[period];
  if (!block || typeof block !== "object") return null;
  const row = (block as Record<string, unknown>)[subjectId];
  return row && typeof row === "object"
    ? (row as Record<string, number | null>)
    : null;
}

/** The window of a preset or custom range, anchored to the minute so a query key is stable. */
export function windowOf(
  state: FormState,
  now: Date = new Date(),
): { time_from: string; time_to: string } | null {
  const end = new Date(now);
  end.setSeconds(0, 0);
  const days: Record<string, number> = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "1y": 365,
  };
  if (state.range === "custom") {
    if (!state.from || !state.to) return null;
    return {
      time_from: new Date(state.from).toISOString(),
      time_to: new Date(state.to).toISOString(),
    };
  }
  const span = days[state.range] ?? 30;
  return {
    time_from: new Date(end.getTime() - span * 86_400_000).toISOString(),
    time_to: end.toISOString(),
  };
}

/** The comparison window: the same length right before the main one, or none. */
export function comparisonOf(
  state: FormState,
  window: { time_from: string; time_to: string } | null,
): { time_from: string; time_to: string } | null {
  if (!window || state.compare !== "previous") return null;
  const from = Date.parse(window.time_from);
  const to = Date.parse(window.time_to);
  return {
    time_from: new Date(from - (to - from)).toISOString(),
    time_to: new Date(from).toISOString(),
  };
}

/** The ids of a group and of every group under it, for "add a group" on a form. */
export function groupWithSubgroups(
  groups: EntityGroup[],
  groupId: string,
): Set<string> {
  const ids = new Set([groupId]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const g of groups) {
      if (g.parent_id && ids.has(g.parent_id) && !ids.has(g.id)) {
        ids.add(g.id);
        grew = true;
      }
    }
  }
  return ids;
}

/** The export dialog's preset for the raw fixes behind a result: the subjects over the main
 * period, as GeoJSON for QGIS, R or Python (plan, section 8.9). */
export function fixesPreset(document: ResultDocument): ExportPreset {
  const main = document.periods.find((p) => p.key === "main");
  return {
    dataset: "positions",
    format: "geojson",
    entityIds: document.subjects.map((s) => s.id),
    from: main?.time_from,
    to: main?.time_to,
  };
}

/** Whether a feature is marked as a management unit by the optional convention
 * (`attributes.management.unit`), so "All management units" can pick them at once. */
export function isManagementUnit(feature: Feature): boolean {
  const management = (feature.attributes as Record<string, unknown> | null)
    ?.management;
  return (
    typeof management === "object" &&
    management !== null &&
    (management as { unit?: unknown }).unit === true
  );
}

/** The grazing use intensity as the document carries it: a local metric grid and, per area,
 * its cells with their animal-hours. */
export interface IntensityGrid {
  origin_lat: number;
  origin_lon: number;
  cell_m: number;
  m_per_deg_lon: number;
  areas: Record<string, [number, number, number][]>;
}

const M_PER_DEG_LAT = 111_320;

/** The intensity cells as square features with their hours and their share of the busiest
 * cell, for a choropleth of use inside the areas (the convention of grazing distribution
 * maps: time per cell over the paddock). */
export function intensityFeatures(document: ResultDocument): GeoJSON.Feature[] {
  const grid = document.summary.intensity as IntensityGrid | undefined;
  if (!grid || !grid.areas) return [];
  const cells = Object.entries(grid.areas).flatMap(([area, list]) =>
    list.map(([ix, iy, hours]) => ({ area, ix, iy, hours })),
  );
  const max = Math.max(0, ...cells.map((c) => c.hours));
  const dx = grid.cell_m / grid.m_per_deg_lon;
  const dy = grid.cell_m / M_PER_DEG_LAT;
  return cells.map((c) => {
    const x0 = grid.origin_lon + c.ix * dx;
    const y0 = grid.origin_lat + c.iy * dy;
    return {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [x0, y0],
            [x0 + dx, y0],
            [x0 + dx, y0 + dy],
            [x0, y0 + dy],
            [x0, y0],
          ],
        ],
      },
      properties: {
        kind: "intensity",
        area_id: c.area,
        hours: c.hours,
        share: max > 0 ? c.hours / max : 0,
      },
    };
  });
}

/** The form filled from a run's stored parameters, so a person adjusts and runs again. The
 * period becomes a custom range with the run's dates; a comparison window is "the period
 * before" (what the form can express); a second herd is not recoverable as a group and is
 * left out. */
export function formStateOfRun(run: AnalysisRun, base: FormState): FormState {
  const p = run.parameters as Record<string, unknown>;
  const list = (key: string): string[] =>
    Array.isArray(p[key]) ? (p[key] as unknown[]).map(String) : [];
  const num = (key: string, fallback: number): number =>
    typeof p[key] === "number" ? (p[key] as number) : fallback;
  const seasons = p.seasons === true;
  return {
    ...base,
    entities: list("entity_ids"),
    group: null,
    type: null,
    range: "custom",
    from: typeof p.time_from === "string" ? p.time_from : null,
    to: typeof p.time_to === "string" ? p.time_to : null,
    compare: seasons ? "seasons" : p.comparison ? "previous" : null,
    method: {
      gap: num("gap_hours", DEFAULT_METHOD.gap),
      speed_max: num("max_speed_mps", DEFAULT_METHOD.speed_max),
      cell: num("cell_m", DEFAULT_METHOD.cell),
      methods: Array.isArray(p.methods)
        ? list("methods").filter((m) => ALL_METHODS.includes(m))
        : ALL_METHODS,
      kde_bandwidth:
        typeof p.kde_bandwidth_m === "number" ? p.kde_bandwidth_m : null,
    },
    grazing: {
      areas: list("feature_ids"),
      weighting: (["equal", "attribute", "metabolic"] as const).includes(
        p.weighting as "equal",
      )
        ? (p.weighting as GrazingOptions["weighting"])
        : "equal",
      weight_key: typeof p.weight_key === "string" ? p.weight_key : null,
      herd_b: null,
      seasons,
      absence: num("min_absence_hours", DEFAULT_GRAZING.absence),
      rest: num("rest_threshold_hours", 0),
    },
  };
}

/** Whether a URL names subjects or areas: a deep link that should open the dialog. */
export function hasFormInput(state: FormState): boolean {
  return (
    state.entities.length > 0 ||
    state.group !== null ||
    state.type !== null ||
    state.grazing.areas.length > 0
  );
}

/** Whole days until a moment, at least one, for "expires in N days". */
export function daysUntil(iso: string, now: number = Date.now()): number {
  return Math.max(1, Math.ceil((Date.parse(iso) - now) / 86_400_000));
}
