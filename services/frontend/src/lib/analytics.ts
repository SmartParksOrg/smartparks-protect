/** Pure helpers for the Data Explorer: time ranges, series naming, client side shaping. */
import type { Series, SeriesResponse } from "@/api/types";

export const RANGE_PRESETS = {
  "24h": { label: "Last 24 hours", hours: 24 },
  "7d": { label: "Last 7 days", hours: 24 * 7 },
  "30d": { label: "Last 30 days", hours: 24 * 30 },
  "90d": { label: "Last 90 days", hours: 24 * 90 },
  "1y": { label: "Last year", hours: 24 * 365 },
} as const;

export type RangePreset = keyof typeof RANGE_PRESETS;

export const BUCKETS = ["auto", "1s", "10s", "1m", "5m", "15m", "1h", "6h", "1d", "7d", "all"] as const;
export const AGGREGATES = ["mean", "min", "max", "median", "sum", "count", "first", "last"] as const;
export type Aggregate = (typeof AGGREGATES)[number];
export const CHART_TYPES = ["line", "scatter", "bar", "histogram", "state"] as const;
export type ChartType = (typeof CHART_TYPES)[number];

/** Zones offered in the picker; the browser's own zone is always first. */
export const TIMEZONES = [
  "UTC",
  "Africa/Johannesburg",
  "Africa/Nairobi",
  "Africa/Lagos",
  "Africa/Kinshasa",
  "Europe/Amsterdam",
  "Europe/London",
  "America/New_York",
  "Asia/Kolkata",
];

export function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** `from`/`to` for a preset, anchored at `now` so a query key stays stable within a minute. */
export function rangeFor(preset: RangePreset, now: Date = new Date()): { from: string; to: string } {
  const to = new Date(Math.floor(now.getTime() / 60_000) * 60_000);
  const from = new Date(to.getTime() - RANGE_PRESETS[preset].hours * 3_600_000);
  return { from: from.toISOString(), to: to.toISOString() };
}

export function formatInZone(iso: string, timezone: string, options?: Intl.DateTimeFormatOptions): string {
  try {
    return new Date(iso).toLocaleString(undefined, { timeZone: timezone, dateStyle: "medium", timeStyle: "short", ...options });
  } catch {
    return new Date(iso).toLocaleString();
  }
}

export function seriesLabel(series: Series, names: Map<string, string>, metricLabels: Map<string, string>): string {
  const owner = series.entity_id ?? series.device_id;
  const ownerName = owner ? names.get(owner) ?? owner.slice(0, 8) : "";
  const metric = metricLabels.get(series.metric_key) ?? series.metric_key;
  return ownerName ? `${metric} · ${ownerName}` : metric;
}

export interface LongRow {
  time: string;
  metric_key: string;
  owner_id: string | null;
  owner_name: string;
  values: Record<string, number | null>;
}

/** The series layout turned into one row per bucket and series, for the table. */
export function toLongRows(response: SeriesResponse, names: Map<string, string>): LongRow[] {
  const rows: LongRow[] = [];
  for (const series of response.series ?? []) {
    const owner = series.entity_id ?? series.device_id ?? null;
    for (const point of series.points) {
      rows.push({ time: point.time, metric_key: series.metric_key, owner_id: owner, owner_name: owner ? names.get(owner) ?? "" : "", values: point.values });
    }
  }
  return rows.sort((a, b) => a.time.localeCompare(b.time));
}

/** Equal width bins over the values of every series, for the histogram chart. */
export function histogram(values: number[], bins = 20): { edges: number[]; counts: number[] } {
  if (values.length === 0) return { edges: [], counts: [] };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = max === min ? 1 : (max - min) / bins;
  const counts = new Array<number>(bins).fill(0);
  for (const v of values) {
    const index = Math.min(bins - 1, Math.floor((v - min) / width));
    counts[index] += 1;
  }
  const edges = Array.from({ length: bins }, (_, i) => min + i * width);
  return { edges, counts };
}

/** Human bucket width from seconds: 3600 gives "1 h". */
export function bucketLabel(seconds: number): string {
  if (seconds >= 86_400) return `${Math.round(seconds / 86_400)} d`;
  if (seconds >= 3_600) return `${Math.round(seconds / 3_600)} h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)} min`;
  return `${seconds} s`;
}
