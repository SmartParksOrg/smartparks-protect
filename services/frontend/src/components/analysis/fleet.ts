import { type ResultDocument, subjectSummary } from "@/lib/analyses";

/** The device performance result as the fleet table and the device sections read it
 * (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md, section 7): levels, figures as words, the
 * order worst first, and the indicators of each area's card. */

export type Level = "ok" | "warn" | "critical" | null;

const ORDER: Record<string, number> = { critical: 0, warn: 1, ok: 2 };

/** The device's headline level: the worst of its indicators. */
export function deviceLevel(
  document: ResultDocument,
  subjectId: string,
): Level {
  const main = subjectSummary(document, "main", subjectId) as Record<
    string,
    unknown
  > | null;
  const level = main?.level;
  return level === "ok" || level === "warn" || level === "critical"
    ? level
    : null;
}

/** A figure as words: shares as percentages, seconds as minutes above two, the rest rounded. */
export function showFigure(value: unknown, key: string): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value !== "number") return String(value);
  if (key.endsWith("_share") || key === "fix_success")
    return `${Math.round(value * 100)}%`;
  if (key.endsWith("_s") && Math.abs(value) >= 120)
    return `${Math.round(value / 60)} min`;
  if (Number.isInteger(value)) return String(value);
  return Math.abs(value) >= 100
    ? value.toFixed(0)
    : Math.abs(value) >= 10
      ? value.toFixed(1)
      : value.toFixed(2);
}

/** The devices of a result, the worst first: by headline level, then by the count of
 * critical and warn indicators, then by name. */
export function orderedSubjects(document: ResultDocument) {
  const weight = (id: string) => {
    const levels = (
      document.summary.levels as
        Record<string, Record<string, string>> | undefined
    )?.[id];
    let score = 0;
    for (const level of Object.values(levels ?? {}))
      score += level === "critical" ? 10 : level === "warn" ? 1 : 0;
    return score;
  };
  return [...document.subjects].sort((a, b) => {
    const la = deviceLevel(document, a.id);
    const lb = deviceLevel(document, b.id);
    const oa = la ? ORDER[la] : 3;
    const ob = lb ? ORDER[lb] : 3;
    if (oa !== ob) return oa - ob;
    const wa = weight(a.id);
    const wb = weight(b.id);
    if (wa !== wb) return wb - wa;
    return a.name.localeCompare(b.name);
  });
}

/** The indicator keys of each area's card, in order. */
export const AREA_CARDS: [string, string[]][] = [
  [
    "health",
    [
      "battery_v",
      "battery_slope_mv_day",
      "days_to_critical",
      "temperature_max_c",
      "hot_hours",
      "reboots",
      "uptime_max_d",
      "error_share",
      "flash_used_percent",
      "moving_share",
      "firmware",
    ],
  ],
  [
    "reporting",
    [
      "expected_fix_s",
      "expected_fix_source",
      "fix_regular_share",
      "declared_fix_s",
      "observed_fix_median_s",
      "missed_fix_share",
      "expected_status_s",
      "missed_status_share",
      "silences",
      "longest_silence_h",
      "messages",
      "invalid_records",
    ],
  ],
  [
    "gnss",
    [
      "attempts",
      "fixes",
      "fix_success",
      "ttf_median_s",
      "ttf_p90_s",
      "satellites_median",
      "few_satellites_share",
      "accuracy_median_m",
      "pdop_median",
      "rejected_share",
      "fixes_per_day",
    ],
  ],
  [
    "network",
    ["lost_uplinks_share", "rssi_p10_dbm", "missed_sessions_share", "sources"],
  ],
];
