import type { ReactNode } from "react";

import type { AnalysisRun } from "@/api/types";
import { AreaCards } from "@/components/analysis/AreaCards";
import {
  DeviceSections,
  FleetTable,
  LevelDefaults,
} from "@/components/analysis/FleetTable";
import {
  DevicePerformanceLimitations,
  GrazingLimitations,
  MovementLimitations,
} from "@/components/analysis/Limitations";
import { RestStrip } from "@/components/analysis/RestStrip";
import { ResultMap } from "@/components/analysis/ResultMap";
import { ResultTable } from "@/components/analysis/ResultTable";
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
    /** In place of the generic chart grid and table list, when the module lays them out
     * itself (device performance folds them per device). */
    charts?: (
      document: ResultDocument,
      run: AnalysisRun,
      colors: Record<string, string>,
    ) => ReactNode;
    tables?: (document: ResultDocument, run: AnalysisRun) => ReactNode;
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

export function devicePerformancePresentation(
  t: Translate,
  projectId: string,
): Presentation {
  const labels = devicePerformanceLabels(t);
  return {
    labels,
    render: {
      summary: (document, _run, colors) => (
        <>
          {document.subjects.length > 1 && (
            <FleetTable document={document} labels={labels} colors={colors} />
          )}
          <DeviceSections document={document} labels={labels} colors={colors} />
        </>
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
      // the charts live in the device sections; the fleet table is the summary block
      charts: () => null,
      tables: (document) => (
        <>
          {document.tables
            .filter((table) => table.key !== "fleet" && table.rows.length > 0)
            .map((table) => (
              <div key={table.key} className="space-y-2">
                <h2 className="text-base font-medium">
                  {labels[table.key] ?? table.key}
                </h2>
                <ResultTable table={table} labels={labels} />
              </div>
            ))}
        </>
      ),
      after: (document) => (
        <>
          <LevelDefaults document={document} labels={labels} />
          <DevicePerformanceLimitations />
        </>
      ),
    },
  };
}

/** The human names of the device performance result's keys (plan, sections 4 and 6). */
export const devicePerformanceLabels = (
  t: Translate,
): Record<string, string> => ({
  device: t("Device"),
  period: t("Period"),
  main: t("This period"),
  comparison: t("Before"),
  level: t("Level"),
  source: t("Data source"),
  channel: t("Channel"),
  flag: t("Error flag"),
  time: t("Time"),
  reason: t("Reason"),
  share: t("Share"),
  sources: t("Data sources"),
  statuses: t("Statuses"),
  battery_v: t("Battery (V)"),
  battery_min_v: t("Lowest battery (V)"),
  battery_slope_mv_day: t("Battery slope (mV/day)"),
  days_to_critical: t("Days to critical"),
  charging_days: t("Charging days"),
  temperature_min_c: t("Lowest temperature (°C)"),
  temperature_median_c: t("Median temperature (°C)"),
  temperature_max_c: t("Highest temperature (°C)"),
  hot_hours: t("Hours above the warn temperature"),
  reboots: t("Reboots"),
  reboots_per_week: t("Reboots per week"),
  uptime_max_d: t("Longest uptime (days)"),
  error_share: t("Statuses with an error"),
  flash_used_percent: t("Flash used (%)"),
  moving_share: t("Statuses with movement"),
  firmware: t("Firmware"),
  expected_fix_s: t("Fix interval set (s)"),
  expected_status_s: t("Status interval set (s)"),
  fixes: t("Fixes"),
  observed_fix_median_s: t("Fix interval seen (s)"),
  observed_fix_p90_s: t("Fix interval, 90th percentile (s)"),
  missed_fix_share: t("Missed fixes"),
  observed_status_median_s: t("Status interval seen (s)"),
  missed_status_share: t("Missed statuses"),
  silences: t("Silences"),
  longest_silence_h: t("Longest silence (h)"),
  longest_silence_ended: t("Longest silence ended"),
  messages: t("Messages"),
  invalid_records: t("Records held invalid"),
  invalid_share: t("Share held invalid"),
  attempts: t("GNSS attempts"),
  fix_success: t("Fix success"),
  ttf_median_s: t("Time to fix (s)"),
  ttf_p90_s: t("Time to fix, 90th percentile (s)"),
  satellites_median: t("Satellites"),
  few_satellites_share: t("Fixes under four satellites"),
  accuracy_median_m: t("Accuracy (m)"),
  accuracy_p90_m: t("Accuracy, 90th percentile (m)"),
  poor_accuracy_share: t("Fixes above the warn accuracy"),
  pdop_median: t("PDOP"),
  rejected_fixes: t("Rejected fixes"),
  rejected_share: t("Rejected fixes share"),
  fixes_per_day: t("Fixes per day"),
  per_day: t("Messages per day"),
  lost_uplinks_share: t("Lost uplinks"),
  gateways: t("Gateways"),
  best_gateway: t("Best gateway"),
  best_gateway_share: t("Best gateway's share"),
  rssi_median_dbm: t("RSSI (dBm)"),
  rssi_p10_dbm: t("RSSI, 10th percentile (dBm)"),
  snr_median_db: t("SNR (dB)"),
  snr_p10_db: t("SNR, 10th percentile (dB)"),
  joins: t("Joins"),
  joins_per_day: t("Joins per day"),
  sessions: t("Satellite sessions"),
  missed_sessions_share: t("Missed sessions"),
  failed_sessions_share: t("Failed sessions"),
  redeliveries: t("Redeliveries"),
  bytes: t("Bytes"),
  fleet: t("Fleet"),
  health: t("Health"),
  reporting: t("Reporting"),
  gnss: t("GNSS"),
  network: t("Network"),
  errors: t("Error flags"),
  battery: t("Battery"),
  temperature: t("Highest temperature per day"),
  time_to_fix: t("Time to fix"),
  accuracy: t("Accuracy of the fixes"),
  satellites: t("Satellites per fix"),
  uplinks_per_day: t("Messages per day"),
  rssi_per_day: t("RSSI per day"),
  sessions_per_day: t("Satellite sessions per day"),
});

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
