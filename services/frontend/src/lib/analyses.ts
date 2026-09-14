import type { AnalysisRun } from "@/api/types";

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
}

export const DEFAULT_RANGE = "30d";

export function readFormState(params: URLSearchParams): FormState {
  return {
    entities: params.getAll("entity"),
    group: params.get("group"),
    type: params.get("type"),
    range: params.get("range") ?? DEFAULT_RANGE,
    from: params.get("from"),
    to: params.get("to"),
    compare: params.get("compare"),
    run: params.get("run"),
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
  if (state.run) params.set("run", state.run);
  return params;
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
