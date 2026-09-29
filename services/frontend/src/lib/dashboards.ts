import type { Series, SeriesResponse } from "@/api/types";
import {
  type Aggregate,
  AGGREGATES,
  RANGE_PRESETS,
  type RangePreset,
} from "@/lib/analytics";
import { scaledUnit } from "@/lib/format";
import { t } from "@/lib/i18nMark";

/** How a metric tile draws its metric (decision D309). */
export const METRIC_DISPLAYS = ["line", "bar", "table", "number"] as const;
export type MetricDisplay = (typeof METRIC_DISPLAYS)[number];
export const METRIC_DISPLAY_LABELS: Record<MetricDisplay, string> = {
  line: t("Line graph"),
  bar: t("Bar graph"),
  table: t("Table, a row per subject"),
  number: t("Latest value as a number"),
};
/** The aggregates a tile offers; the time of the last value is the table's own. */
export const TILE_AGGREGATES = AGGREGATES;
export const AGGREGATE_LABELS: Record<Aggregate, string> = {
  mean: t("Mean"),
  min: t("Lowest"),
  max: t("Highest"),
  median: t("Median"),
  sum: t("Sum"),
  count: t("Count"),
  first: t("First"),
  last: t("Last"),
};
/** The bounds of the API's `MetricTileOptions`. */
export const MAX_TILE_METRICS = 4;
export const MAX_TILE_SUBJECTS = 20;
/** Latest values a number tile shows before it says how many more there are. */
export const MAX_TILE_NUMBERS = 6;

export interface MetricTileOptions {
  metrics: string[];
  entity_ids: string[];
  device_ids: string[];
  group_by: "entity" | "device";
  range: RangePreset;
  aggregate: Aggregate;
  display: MetricDisplay;
}

export const METRIC_TILE_DEFAULTS: MetricTileOptions = {
  metrics: [],
  entity_ids: [],
  device_ids: [],
  group_by: "entity",
  range: "7d",
  aggregate: "mean",
  display: "line",
};

const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];

/** A tile's stored options read with their defaults; whatever the document holds that the
 * tile does not know falls back, so an older or a hand-made tile still draws. */
export function readMetricOptions(
  raw: Record<string, unknown> | null | undefined,
): MetricTileOptions {
  const o = raw ?? {};
  const range = String(o.range ?? "");
  const aggregate = String(o.aggregate ?? "");
  const display = String(o.display ?? "");
  return {
    metrics: strings(o.metrics).slice(0, MAX_TILE_METRICS),
    entity_ids: strings(o.entity_ids).slice(0, MAX_TILE_SUBJECTS),
    device_ids: strings(o.device_ids).slice(0, MAX_TILE_SUBJECTS),
    group_by: o.group_by === "device" ? "device" : "entity",
    range: range in RANGE_PRESETS ? (range as RangePreset) : "7d",
    aggregate: (AGGREGATES as readonly string[]).includes(aggregate)
      ? (aggregate as Aggregate)
      : "mean",
    display: (METRIC_DISPLAYS as readonly string[]).includes(display)
      ? (display as MetricDisplay)
      : "line",
  };
}

/** The options as the API takes them: the subjects of the kind the tile groups by alone, and
 * one metric for a single number. */
export function writeMetricOptions(
  options: MetricTileOptions,
): Record<string, unknown> {
  return {
    ...options,
    metrics:
      options.display === "number"
        ? options.metrics.slice(0, 1)
        : options.metrics,
    entity_ids: options.group_by === "entity" ? options.entity_ids : [],
    device_ids: options.group_by === "device" ? options.device_ids : [],
  };
}

/** The series request of a tile over a window. A graph asks for its aggregate per bucket; a
 * table and a number ask for the whole period as one bucket, with the latest value and the
 * moment it was measured. */
export function metricTileQuery(
  options: MetricTileOptions,
  window: { from: string; to: string },
): string {
  const q = new URLSearchParams();
  for (const m of options.metrics) q.append("metric", m);
  if (options.group_by === "entity")
    for (const id of options.entity_ids) q.append("entity_id", id);
  else for (const id of options.device_ids) q.append("device_id", id);
  q.set("group_by", options.group_by);
  q.set("from", window.from);
  q.set("to", window.to);
  q.set("layout", "series");
  if (options.display === "table") {
    q.set("bucket", "all");
    for (const a of ["last", "last_at", "mean", "min", "max"])
      q.append("agg", a);
  } else if (options.display === "number") {
    q.set("bucket", "all");
    for (const a of ["last", "last_at"]) q.append("agg", a);
  } else {
    q.append("agg", options.aggregate);
  }
  return q.toString();
}

/** The response with every value in the unit people read (a speed in km/h, decision D297):
 * the registry keeps the unit a device counts in, a chart shows the other. A count stays a
 * count and a moment a moment. */
export function inReadUnits(response: SeriesResponse): SeriesResponse {
  const unscaled = new Set(["count", "last_at"]);
  return {
    ...response,
    series: (response.series ?? []).map((s) => {
      const scaled = scaledUnit(s.unit);
      if (scaled.factor === 1 && scaled.unit === (s.unit ?? null)) return s;
      return {
        ...s,
        unit: scaled.unit,
        points: s.points.map((p) => ({
          ...p,
          values: Object.fromEntries(
            Object.entries(p.values).map(([key, value]) => [
              key,
              typeof value === "number" && !unscaled.has(key)
                ? value * scaled.factor
                : value,
            ]),
          ),
        })),
      };
    }),
  };
}

export interface MetricRow {
  key: string;
  subject: string;
  metric: string;
  unit: string | null;
  last: number | null;
  /** When the last value was measured, ISO; null when the period holds none. */
  lastAt: string | null;
  mean: number | null;
  min: number | null;
  max: number | null;
}

/** A row per subject and metric from a whole-period response, by subject name and then in
 * the order the tile names its metrics. */
export function metricRows(
  response: SeriesResponse | undefined,
  names: Map<string, string>,
  metricLabels: Map<string, string>,
  order: string[],
): MetricRow[] {
  const value = (s: Series, key: string): number | null => {
    const v = s.points[0]?.values[key];
    return typeof v === "number" ? v : null;
  };
  const rows = (response?.series ?? []).map((s) => {
    const owner = s.entity_id ?? s.device_id ?? "";
    const at = value(s, "last_at");
    return {
      key: `${owner}|${s.metric_key}`,
      subject: names.get(owner) ?? owner.slice(0, 8),
      metric: s.metric_key,
      unit: s.unit ?? null,
      last: value(s, "last"),
      lastAt: at === null ? null : new Date(at * 1000).toISOString(),
      mean: value(s, "mean"),
      min: value(s, "min"),
      max: value(s, "max"),
    };
  });
  const place = (key: string) => {
    const at = order.indexOf(key);
    return at < 0 ? order.length : at;
  };
  return rows
    .sort(
      (a, b) =>
        a.subject.localeCompare(b.subject) || place(a.metric) - place(b.metric),
    )
    .map((row) => ({
      ...row,
      metric: metricLabels.get(row.metric) ?? row.metric,
    }));
}

/** A value of a tile in few characters: whole numbers as they are, the rest to two or three
 * figures that matter. */
export function tileNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "";
  if (Number.isInteger(value)) return String(value);
  const size = Math.abs(value);
  if (size >= 100) return value.toFixed(1);
  if (size >= 1) return value.toFixed(2);
  return value.toFixed(3);
}
