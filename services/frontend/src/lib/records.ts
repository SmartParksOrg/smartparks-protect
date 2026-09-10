import type { RecordRow } from "@/api/types";
import {
  RANGE_PRESETS,
  type RangePreset,
  browserTimezone,
  rangeFor,
} from "@/lib/analytics";

/**
 * The records view (phase 20, decisions D142 to D146): its URL state, the columns the loaded
 * rows carry, and the series a column makes. Everything the view shows comes from the URL, so
 * a link and a saved view reproduce it.
 */
export interface RecordsState {
  entities: string[];
  devices: string[];
  range: RangePreset | "custom" | "assignment";
  from: string | null;
  to: string | null;
  timezone: string;
  // the moment a link came from (a track point, a Data tab at a time): that row is highlighted
  at?: string | null;
  /** The device's own fixes (absent, the default) or those plus the network's locations (D163). */
  sources?: "device" | "all";
}

const HALF_WINDOW_MS = 12 * 3600_000;

function validTime(raw: string | null): string | null {
  const ms = raw ? Date.parse(raw) : NaN;
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null;
}

export function readRecordsState(params: URLSearchParams): RecordsState {
  const range = params.get("range") ?? "7d";
  const from = params.get("from");
  const to = params.get("to");
  return {
    entities: params.getAll("entity"),
    devices: params.getAll("device"),
    range:
      range === "custom" || range === "assignment"
        ? range
        : ((range in RANGE_PRESETS ? range : "7d") as RangePreset),
    from,
    to,
    timezone: params.get("tz") ?? browserTimezone(),
    at: validTime(params.get("at")),
    ...(params.get("sources") === "all" ? { sources: "all" as const } : {}),
  };
}

export function writeRecordsState(state: RecordsState): URLSearchParams {
  const params = new URLSearchParams();
  params.set("mode", "table");
  for (const e of state.entities) params.append("entity", e);
  for (const d of state.devices) params.append("device", d);
  params.set("range", state.range);
  if (state.range === "custom") {
    if (state.from) params.set("from", state.from);
    if (state.to) params.set("to", state.to);
  }
  params.set("tz", state.timezone);
  if (state.at) params.set("at", state.at);
  if (state.sources === "all") params.set("sources", "all");
  return params;
}

/** The records view of one selection, for the links that land there (decision D145): the Data
 * tabs, the map's point panel and the search palette. With `at`, the twelve hours either side
 * of that moment and the row at it highlighted; without, the last 30 days. */
export function recordsHref(
  projectId: string,
  selection: { entities?: string[]; devices?: string[]; at?: string | null },
): string {
  const at = validTime(selection.at ?? null);
  const ms = at ? Date.parse(at) : 0;
  const params = writeRecordsState({
    entities: selection.entities ?? [],
    devices: selection.devices ?? [],
    range: at ? "custom" : "30d",
    from: at ? new Date(ms - HALF_WINDOW_MS).toISOString() : null,
    to: at ? new Date(ms + HALF_WINDOW_MS).toISOString() : null,
    timezone: browserTimezone(),
    at,
  });
  return `/projects/${projectId}/analyze/explorer?${params.toString()}`;
}

/** What a `datetime-local` input can show: a value written by the input as it is, an ISO time
 * with a zone (a link's window) as the browser's local minute. */
export function inputValue(value: string | null): string {
  if (!value) return "";
  if (!/(Z|[+-]\d\d:\d\d)$/.test(value)) return value.slice(0, 16);
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** The window the selection covers: a preset, a custom range, or since an entity's assignment
 * (`assignedSince`, when known; the fallback is the 30 day preset). */
export function windowFor(
  state: RecordsState,
  assignedSince: string | null | undefined,
  now: Date = new Date(),
): { from: string; to: string } {
  if (state.range === "custom" && state.from && state.to)
    return {
      from: new Date(state.from).toISOString(),
      to: new Date(state.to).toISOString(),
    };
  if (state.range === "assignment" && assignedSince)
    return { from: assignedSince, to: now.toISOString() };
  const preset: RangePreset =
    state.range === "custom" || state.range === "assignment"
      ? "30d"
      : state.range;
  return rangeFor(preset, now);
}

export type CellValue = number | string | boolean | null;

export interface RecordColumn {
  key: string;
  label: string;
  unit?: string | null;
  kind: "fixed" | "metric" | "state";
  numeric: boolean;
}

const FIXED: RecordColumn[] = [
  { key: "time", label: "Time", kind: "fixed", numeric: false },
  { key: "entity", label: "Entity", kind: "fixed", numeric: false },
  { key: "device", label: "Device", kind: "fixed", numeric: false },
  { key: "lat", label: "Latitude", kind: "fixed", numeric: true },
  { key: "lon", label: "Longitude", kind: "fixed", numeric: true },
  {
    key: "accuracy_m",
    label: "Accuracy",
    unit: "m",
    kind: "fixed",
    numeric: true,
  },
  {
    key: "speed_kmh",
    label: "Speed",
    unit: "km/h",
    kind: "fixed",
    numeric: true,
  },
  {
    key: "altitude_m",
    label: "Altitude",
    unit: "m",
    kind: "fixed",
    numeric: true,
  },
];

/** The columns the loaded rows carry: the fixed ones, then a column per metric key seen (in
 * the order first seen, with the registry's label and unit), then the state fields seen. */
export function columnsOf(
  rows: RecordRow[],
  metricLabels: Map<string, { label: string; unit: string | null }>,
): RecordColumn[] {
  const metricKeys = new Map<string, boolean>();
  const stateKeys = new Map<string, boolean>();
  for (const row of rows) {
    for (const [key, value] of Object.entries(row.measurements ?? {}))
      metricKeys.set(
        key,
        (metricKeys.get(key) ?? true) &&
          (value === null || typeof value === "number"),
      );
    for (const [key, value] of Object.entries(row.state ?? {}))
      stateKeys.set(
        key,
        (stateKeys.get(key) ?? true) &&
          (value === null || typeof value === "number"),
      );
  }
  return [
    ...FIXED,
    ...[...metricKeys].map(([key, numeric]) => ({
      key: `m:${key}`,
      label: metricLabels.get(key)?.label ?? key,
      unit: metricLabels.get(key)?.unit ?? null,
      kind: "metric" as const,
      numeric,
    })),
    ...[...stateKeys].map(([key, numeric]) => ({
      key: `s:${key}`,
      label: key,
      kind: "state" as const,
      numeric,
    })),
  ];
}

/** One cell's raw value. */
export function cellOf(row: RecordRow, column: RecordColumn): CellValue {
  switch (column.key) {
    case "time":
      return row.time;
    case "entity":
      return row.entity_name ?? null;
    case "device":
      return row.device_name ?? null;
    case "lat":
      return row.position?.lat ?? null;
    case "lon":
      return row.position?.lon ?? null;
    case "accuracy_m":
      return row.position?.accuracy_m ?? null;
    case "speed_kmh":
      return row.position?.speed_mps != null
        ? row.position.speed_mps * 3.6
        : null;
    case "altitude_m":
      return row.position?.altitude_m ?? null;
    default: {
      const raw =
        column.kind === "metric"
          ? row.measurements?.[column.key.slice(2)]
          : row.state?.[column.key.slice(2)];
      if (raw === undefined || raw === null) return null;
      if (
        typeof raw === "number" ||
        typeof raw === "string" ||
        typeof raw === "boolean"
      )
        return raw;
      return JSON.stringify(raw);
    }
  }
}

export function formatCell(value: CellValue): string {
  if (value === null) return "";
  if (typeof value === "number")
    return Number.isInteger(value)
      ? String(value)
      : value.toFixed(value < 10 ? 3 : 2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return value;
}

/** The numeric series of a column over the loaded rows, oldest first, for a sparkline. */
export function seriesOf(
  rows: RecordRow[],
  column: RecordColumn,
): { time: string; value: number }[] {
  const points: { time: string; value: number }[] = [];
  for (const row of rows) {
    const value = cellOf(row, column);
    if (typeof value === "number" && Number.isFinite(value))
      points.push({ time: row.time, value });
  }
  return points.reverse();
}
