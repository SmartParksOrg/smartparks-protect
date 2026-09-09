import type { RecordRow, SeriesResponse } from "@/api/types";
import type { TrackLayer } from "@/components/map/layers";
import {
  type Aggregate,
  AGGREGATES,
  type ChartType,
  CHART_TYPES,
} from "@/lib/analytics";
import {
  cellOf,
  type RecordColumn,
  readRecordsState,
  type RecordsState,
  writeRecordsState,
} from "@/lib/records";

/**
 * Explore as one canvas (phase 21, decisions D150 to D155): one selection looked at three ways.
 * The state is the URL, so a link and a saved view reproduce it; the table's state (entities,
 * devices, period, timezone, the marked moment) is shared with the chart and the map, and the
 * chart adds its metrics, kind and the aggregate read's bucket and aggregates.
 */
export type ExploreMode = "table" | "chart" | "map";
export const MODES: ExploreMode[] = ["table", "chart", "map"];

/** Loaded rows draw raw points up to this many; above, the chart takes the aggregate read and
 * the map the track read (decision D155). */
export const CANVAS_BOUND = 50_000;
/** Metrics on the chart at once: one grid each. */
export const MAX_CHART_METRICS = 8;
export const DEFAULT_CHART_METRICS = 4;
const DEFAULT_AGGREGATES: Aggregate[] = ["mean", "min", "max", "count"];

export interface ExploreState extends RecordsState {
  mode: ExploreMode;
  /** Metric keys on the chart; empty means the first numeric columns of the loaded rows. */
  metrics: string[];
  chart: ChartType;
  /** The metric on the x axis of a scatter chart; null means time. */
  xMetric: string | null;
  /** Metrics drawn against the secondary (right) axis. */
  secondary: string[];
  bucket: string;
  aggregates: Aggregate[];
}

export function readExploreState(params: URLSearchParams): ExploreState {
  const raw = params.get("mode");
  // the tabs of v2.4.0 (`records`, `analysis`) open as the table and the chart
  const mode: ExploreMode =
    raw === "chart" || raw === "analysis"
      ? "chart"
      : raw === "map"
        ? "map"
        : "table";
  const chart = params.get("chart") ?? "line";
  const agg = params
    .getAll("agg")
    .filter((a): a is Aggregate =>
      (AGGREGATES as readonly string[]).includes(a),
    );
  return {
    ...readRecordsState(params),
    mode,
    metrics: params.getAll("metric").slice(0, MAX_CHART_METRICS),
    chart: ((CHART_TYPES as readonly string[]).includes(chart)
      ? chart
      : "line") as ChartType,
    xMetric: params.get("x"),
    secondary: params.getAll("y2"),
    bucket: params.get("bucket") ?? "auto",
    aggregates: agg.length ? agg : DEFAULT_AGGREGATES,
  };
}

export function writeExploreState(state: ExploreState): URLSearchParams {
  const params = writeRecordsState(state);
  params.set("mode", state.mode);
  for (const m of state.metrics) params.append("metric", m);
  if (state.chart !== "line") params.set("chart", state.chart);
  if (state.xMetric) params.set("x", state.xMetric);
  for (const m of state.secondary) params.append("y2", m);
  if (state.bucket !== "auto") params.set("bucket", state.bucket);
  if (state.aggregates.join(",") !== DEFAULT_AGGREGATES.join(","))
    for (const a of state.aggregates) params.append("agg", a);
  return params;
}

/** A saved view is its search parameters (decision D42): `{key: [values]}`. */
export function paramsOfView(view: Record<string, string[]>): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, values] of Object.entries(view))
    for (const v of values) params.append(key, v);
  return params;
}

export function viewOfParams(
  params: URLSearchParams,
): Record<string, string[]> {
  return Object.fromEntries(
    Array.from(new Set(params.keys())).map((k) => [k, params.getAll(k)]),
  );
}

/** The metric columns a chart can draw: numeric measurements, not the fix's own numbers. */
const NOT_CHARTED = new Set(["lat", "lon", "accuracy_m", "altitude_m"]);

export function chartableColumns(columns: RecordColumn[]): RecordColumn[] {
  return columns.filter(
    (c) => c.kind === "metric" && c.numeric && !NOT_CHARTED.has(c.key),
  );
}

/** The metric keys on the chart: the chosen ones that are loaded, else the first few. */
export function chartMetrics(
  chosen: string[],
  columns: RecordColumn[],
): string[] {
  const available = chartableColumns(columns).map((c) => c.key.slice(2));
  if (chosen.length) return chosen.filter((m) => available.includes(m));
  return available.slice(0, DEFAULT_CHART_METRICS);
}

export interface ChartSeries {
  ownerId: string;
  name: string;
  /** `[time in ms, value]`, oldest first; a scatter point carries the time third. */
  data: number[][];
}

export interface ChartGroup {
  metric: string;
  label: string;
  unit: string | null;
  series: ChartSeries[];
}

function ownerOf(row: RecordRow): { id: string; name: string } {
  const id = row.entity_id ?? row.device_id;
  return {
    id,
    name: row.entity_name ?? row.device_name ?? row.device_id.slice(0, 8),
  };
}

function numberOf(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean") return value ? 1 : 0;
  return null;
}

/** One group per metric, one series per owner, from the loaded rows. */
export function chartGroups(
  rows: RecordRow[],
  metrics: string[],
  columns: RecordColumn[],
): ChartGroup[] {
  const byKey = new Map(columns.map((c) => [c.key, c]));
  const groups: ChartGroup[] = [];
  for (const metric of metrics) {
    const column = byKey.get(`m:${metric}`);
    if (!column) continue;
    const series = new Map<string, ChartSeries>();
    for (const row of rows) {
      const value = numberOf(cellOf(row, column));
      if (value === null) continue;
      const owner = ownerOf(row);
      let s = series.get(owner.id);
      if (!s) {
        s = { ownerId: owner.id, name: owner.name, data: [] };
        series.set(owner.id, s);
      }
      s.data.push([Date.parse(row.time), value]);
    }
    for (const s of series.values()) s.data.sort((a, b) => a[0] - b[0]);
    groups.push({
      metric,
      label: column.label,
      unit: column.unit ?? null,
      series: [...series.values()],
    });
  }
  return groups;
}

/** One metric against another per owner, from the moments that carry both. */
export function scatterGroup(
  rows: RecordRow[],
  xMetric: string,
  yMetric: string,
  columns: RecordColumn[],
): ChartGroup | null {
  const byKey = new Map(columns.map((c) => [c.key, c]));
  const x = byKey.get(`m:${xMetric}`);
  const y = byKey.get(`m:${yMetric}`);
  if (!x || !y) return null;
  const series = new Map<string, ChartSeries>();
  for (const row of rows) {
    const xv = numberOf(cellOf(row, x));
    const yv = numberOf(cellOf(row, y));
    if (xv === null || yv === null) continue;
    const owner = ownerOf(row);
    let s = series.get(owner.id);
    if (!s) {
      s = { ownerId: owner.id, name: owner.name, data: [] };
      series.set(owner.id, s);
    }
    s.data.push([xv, yv, Date.parse(row.time)]);
  }
  return {
    metric: yMetric,
    label: y.label,
    unit: y.unit ?? null,
    series: [...series.values()],
  };
}

/** The aggregate read as chart groups, for a selection above the canvas bound. */
export function groupsFromSeries(
  response: SeriesResponse,
  names: Map<string, string>,
  metricLabels: Map<string, string>,
  aggregate: string,
): ChartGroup[] {
  const groups = new Map<string, ChartGroup>();
  for (const s of response.series ?? []) {
    const ownerId = s.entity_id ?? s.device_id ?? "";
    let group = groups.get(s.metric_key);
    if (!group) {
      group = {
        metric: s.metric_key,
        label: metricLabels.get(s.metric_key) ?? s.metric_key,
        unit: s.unit ?? null,
        series: [],
      };
      groups.set(s.metric_key, group);
    }
    group.series.push({
      ownerId,
      name: names.get(ownerId) ?? ownerId.slice(0, 8),
      data: s.points
        .map((p) => [Date.parse(p.time), p.values[aggregate] ?? null])
        .filter((d): d is number[] => d[1] !== null),
    });
  }
  return [...groups.values()];
}

/** The time of the loaded row nearest to a moment; the rows come newest first. */
export function nearestRowTime(rows: RecordRow[], ms: number): string | null {
  if (rows.length === 0) return null;
  let lo = 0;
  let hi = rows.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Date.parse(rows[mid].time) > ms) lo = mid + 1;
    else hi = mid;
  }
  const candidates = [rows[lo], rows[lo - 1]].filter(Boolean);
  let best = candidates[0];
  for (const c of candidates)
    if (
      Math.abs(Date.parse(c.time) - ms) < Math.abs(Date.parse(best.time) - ms)
    )
      best = c;
  return best.time;
}

/** The tracks of the loaded rows: one per owner (the entity, else the device), oldest first. */
export function tracksOf(rows: RecordRow[]): TrackLayer[] {
  const byOwner = new Map<
    string,
    { kind: "entity" | "device"; coordinates: number[][]; times: string[] }
  >();
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    if (!row.position) continue;
    const owner = ownerOf(row);
    let track = byOwner.get(owner.id);
    if (!track) {
      track = {
        kind: row.entity_id ? "entity" : "device",
        coordinates: [],
        times: [],
      };
      byOwner.set(owner.id, track);
    }
    track.coordinates.push([row.position.lon, row.position.lat]);
    track.times.push(row.time);
  }
  return [...byOwner.entries()].map(([entityId, track]) => ({
    entityId,
    kind: track.kind,
    geometry:
      track.coordinates.length > 1
        ? { type: "LineString", coordinates: track.coordinates }
        : { type: "MultiPoint", coordinates: track.coordinates },
    times: track.times,
  }));
}

/** The bounding box of the tracks, `[[west, south], [east, north]]`, or null without points. */
export function boundsOfTracks(
  tracks: TrackLayer[],
): [[number, number], [number, number]] | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const track of tracks) {
    const coordinates =
      track.geometry.type === "LineString" ||
      track.geometry.type === "MultiPoint"
        ? track.geometry.coordinates
        : [];
    for (const [lon, lat] of coordinates) {
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
  }
  return Number.isFinite(west)
    ? [
        [west, south],
        [east, north],
      ]
    : null;
}

/** The point of each track at or before a moment: the marked moment on the map. */
export function pointsAt(
  tracks: TrackLayer[],
  ms: number,
): { ownerId: string; time: string }[] {
  const out: { ownerId: string; time: string }[] = [];
  for (const track of tracks) {
    let found: string | null = null;
    for (const time of track.times) {
      if (Date.parse(time) > ms) break;
      found = time;
    }
    if (found) out.push({ ownerId: track.entityId, time: found });
  }
  return out;
}
