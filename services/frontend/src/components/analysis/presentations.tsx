import type { ReactNode } from "react";

import type { AnalysisRun } from "@/api/types";
import { AreaCards } from "@/components/analysis/AreaCards";
import {
  GrazingLimitations,
  MovementLimitations,
} from "@/components/analysis/Limitations";
import { RestStrip } from "@/components/analysis/RestStrip";
import { ResultMap } from "@/components/analysis/ResultMap";
import { SubjectCards } from "@/components/analysis/SubjectCards";
import type { ResultDocument } from "@/lib/analyses";

type Translate = (k: string) => string;

/** How a module's results read: the human names of its keys and the blocks of its own (a
 * summary in place of the flat list, a map beside it, what comes after the tables). */
export interface Presentation {
  labels: Record<string, string>;
  render: {
    summary: (
      document: ResultDocument,
      run: AnalysisRun,
      colors: Record<string, string>,
    ) => ReactNode;
    map: (
      document: ResultDocument,
      run: AnalysisRun,
      colors: Record<string, string>,
    ) => ReactNode;
    after: (document: ResultDocument, run: AnalysisRun) => ReactNode;
  };
}

/** The figures on a movement subject's card, with their unit. */
export const MOVEMENT_CARD_METRICS: [string, string][] = [
  ["distance_km", "km"],
  ["daily_distance_km", "km/day"],
  ["median_speed_mps", "m/s"],
  ["stationary_share", "%"],
  ["mcp95_ha", "ha"],
  ["kde95_ha", "ha"],
  ["fixes", ""],
];

export function movementPresentation(
  t: Translate,
  projectId: string,
): Presentation {
  const labels = movementLabels(t);
  return {
    labels,
    render: {
      summary: (document, _run, colors) => (
        <SubjectCards
          document={document}
          labels={labels}
          metrics={MOVEMENT_CARD_METRICS}
          colors={colors}
        />
      ),
      map: (document, run, colors) => (
        <ResultMap
          projectId={projectId}
          runId={run.id}
          document={document}
          labels={labels}
          colors={colors}
        />
      ),
      after: () => <MovementLimitations />,
    },
  };
}

export function grazingPresentation(
  t: Translate,
  projectId: string,
): Presentation {
  const labels = grazingLabels(t);
  return {
    labels,
    render: {
      summary: (document) => <AreaCards document={document} labels={labels} />,
      map: (document, run, colors) => (
        <ResultMap
          projectId={projectId}
          runId={run.id}
          document={document}
          labels={labels}
          colors={colors}
        />
      ),
      after: (document, run) => (
        <>
          <RestStrip
            document={document}
            restThreshold={Number(
              (run.parameters as { rest_threshold_hours?: number })
                .rest_threshold_hours ?? 0,
            )}
          />
          <GrazingLimitations />
        </>
      ),
    },
  };
}

/** The human names of the movement result's keys. */
export const movementLabels = (t: Translate): Record<string, string> => ({
  subject: t("Subject"),
  period: t("Period"),
  main: t("This period"),
  comparison: t("Before"),
  mean: t("Mean"),
  sd: t("Standard deviation"),
  fixes: t("Fixes"),
  days_with_data: t("Days with data"),
  median_interval_min: t("Sampling interval (min)"),
  distance_km: t("Distance (km)"),
  daily_distance_km: t("Daily distance (km)"),
  displacement_km: t("Displacement (km)"),
  max_displacement_km: t("Farthest from the start (km)"),
  mean_speed_mps: t("Mean speed (m/s)"),
  median_speed_mps: t("Median speed (m/s)"),
  p95_speed_mps: t("95th percentile speed (m/s)"),
  stationary_share: t("Stationary share"),
  moving_share: t("Moving share"),
  stationary_periods: t("Stationary periods"),
  day_distance_km: t("Distance by day (km)"),
  night_distance_km: t("Distance by night (km)"),
  mcp95_ha: t("MCP 95% (ha)"),
  kde50_ha: t("KDE 50% (ha)"),
  kde95_ha: t("KDE 95% (ha)"),
  kde_bandwidth_m: t("KDE bandwidth (m)"),
  hotspot_count: t("Hotspots"),
  cluster_count: t("Clusters"),
  missing_share: t("Missing fixes share"),
  excluded_fixes: t("Excluded fixes"),
  daily_distance: t("Daily distance"),
  speed_histogram: t("Speed"),
  hour_profile: t("Activity by hour"),
  turning: t("Turning angles"),
  nsd: t("Net squared displacement"),
  day_night: t("Day and night"),
  summary: t("Summary"),
});

/** The human names of the grazing result's keys; every header says use, not grazing. */
export const grazingLabels = (t: Translate): Record<string, string> => ({
  area: t("Area"),
  period: t("Period"),
  herd: t("Herd"),
  animal: t("Animal"),
  metric: t("Figure"),
  main: t("This period"),
  comparison: t("Before"),
  change_percent: t("Change (%)"),
  area_a: t("Area"),
  area_b: t("Overlaps with"),
  hectares: t("Hectares"),
  animal_hours: t("Animal-hours"),
  animal_days: t("Animal-days"),
  animal_hours_per_ha: t("Use (animal-hours per ha)"),
  animal_days_per_ha: t("Use (animal-days per ha)"),
  weighted_animal_days_per_ha: t("Weighted use (per ha)"),
  relative_pressure: t("Relative pressure"),
  pressure_rank: t("Rank"),
  share_of_herd_time: t("Share of herd time"),
  animals_used: t("Animals that used it"),
  visits: t("Visits"),
  mean_visit_hours: t("Mean visit (hours)"),
  use_days: t("Use days"),
  rest_days: t("Rest days"),
  longest_rest_days: t("Longest rest (days)"),
  last_use: t("Last use"),
  hours_since_last_use: t("Hours since last use"),
  hotspot_count: t("Hotspots"),
  hours: t("Hours"),
  weighted_hours: t("Weighted hours"),
  first_use: t("First use"),
  days_used: t("Days used"),
  areas: t("Areas"),
  animals: t("Animals"),
  overlaps: t("Overlaps"),
  changes: t("Change against the period before"),
  timeline: t("Daily animal-hours"),
  pressure: t("Use per hectare"),
  summary: t("Summary"),
});
