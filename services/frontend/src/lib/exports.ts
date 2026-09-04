/** Export datasets and the preset an export dialog can be opened with. */
import type { Aggregate, RangePreset } from "@/lib/analytics";

export const DATASETS = {
  positions: { label: "Positions", formats: ["csv", "xlsx", "json", "geojson", "gpx"] },
  measurements: { label: "Measurements", formats: ["csv", "xlsx", "json"] },
  aggregates: { label: "Aggregates (Data Explorer series)", formats: ["csv", "xlsx", "json"] },
  source_events: { label: "Source events (raw)", formats: ["csv", "xlsx", "json"] },
  movebank_events: { label: "Movebank event data (positions)", formats: ["csv", "xlsx", "json"] },
  movebank_reference: { label: "Movebank reference data (animals, tags, deployments)", formats: ["csv", "xlsx", "json"] },
} as const;
export type Dataset = keyof typeof DATASETS;

export interface ExportPreset {
  dataset?: Dataset;
  format?: string;
  range?: RangePreset;
  from?: string;
  to?: string;
  entityIds?: string[];
  metricKeys?: string[];
  bucket?: string;
  aggregates?: Aggregate[];
  layout?: "long" | "wide";
  timezone?: string;
}

/** Query string for a direct export: repeated keys for the list parameters. */
export function directExportQuery(params: Record<string, unknown>): string {
  const url = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) for (const v of value) url.append(key, String(v));
    else url.set(key, String(value));
  }
  return url.toString();
}
