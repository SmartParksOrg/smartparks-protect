import type { AnalysisRun, EntityGroup } from "@/api/types";
import { trackColor } from "@/components/map/layers";

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
          : methods
              .split(",")
              .filter((m) => ALL_METHODS.includes(m)),
      kde_bandwidth: params.get("kde")
        ? numberOr(params.get("kde"), 0) || null
        : null,
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
  if (state.run) params.set("run", state.run);
  return params;
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

/** The colour of a subject everywhere on the page: the map's track colour, so the polygon,
 * the track and the chart line of one animal agree. */
export function subjectColor(subjectId: string): string {
  return trackColor(subjectId);
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
