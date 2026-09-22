import type { Metric } from "@/api/types";

/** What one trend shows: the metric, its words and how its axis is stepped. */
export interface TrendSpec {
  metric: string;
  label: string;
  unit: string;
  /** Decimals of the values shown; from the axis step when absent. */
  decimals?: number;
  /** The axis step, so the labels never crowd; a round step from the data when absent. */
  step?: number;
  /** A floor for the axis (zero for movement: a flat line at zero means still). */
  floor?: number;
  /** A factor on the stored value before it is shown (seconds to days for the uptime). */
  scale?: number;
  /** A fixed top for the axis: a trap's door is 0 or 1 and nothing above. */
  ceiling?: number;
  /** Words for the values instead of numbers (0 open, 1 closed), on the axis and the tooltip. */
  words?: Record<number, string>;
  /** Drawn as steps rather than slopes: a door is open or shut, never half way. */
  stepped?: boolean;
  ariaLabel: string;
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** A round axis step that cuts the range into two to five intervals: 0.05 for a battery
 * between 3.7 and 3.9 V, 5 for a temperature between 12 and 31 °C; 1 for a flat line. */
export function niceStep(low: number, high: number): number {
  const range = high - low;
  if (!(range > 1e-9)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(range / 3));
  for (const n of [1, 2, 5]) {
    const step = n * magnitude;
    if (range / step <= 5) return step;
  }
  return 10 * magnitude;
}

/** The decimals a step needs: 0.05 shows two, 5 shows none. */
export function decimalsFor(step: number): number {
  return Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
}

/** The trends with a shape of their own: the battery's fine steps, the movement's floor at
 * zero, the uptime in days. `movement` is the health line's name for the `activity` metric. */
const SPECIAL: Record<string, (t: Translate) => TrendSpec> = {
  battery_voltage: (t) => ({
    metric: "battery_voltage",
    label: t("Battery"),
    unit: "V",
    decimals: 2,
    step: 0.05,
    ariaLabel: t("Battery voltage over the period"),
  }),
  activity: (t) => ({
    metric: "activity",
    label: t("Movement"),
    unit: "m/s²",
    decimals: 1,
    step: 0.5,
    floor: 0,
    ariaLabel: t("Movement over the period"),
  }),
  uptime: (t) => ({
    metric: "uptime",
    label: t("Uptime"),
    unit: "d",
    decimals: 1,
    step: 1,
    floor: 0,
    scale: 1 / 86_400,
    ariaLabel: t("Uptime over the period"),
  }),
};
SPECIAL.heart_rate = (t) => ({
  metric: "heart_rate",
  label: t("Heart rate"),
  unit: "bpm",
  decimals: 0,
  step: 10,
  floor: 0,
  ariaLabel: t("Heart rate over the period"),
});
SPECIAL.fence_voltage = (t) => ({
  metric: "fence_voltage",
  label: t("Fence voltage"),
  unit: "kV",
  decimals: 2,
  step: 0.5,
  floor: 0,
  scale: 0.001,
  ariaLabel: t("Fence voltage over the period"),
});
SPECIAL.fence_pulse_count = (t) => ({
  metric: "fence_pulse_count",
  label: t("Fence pulses"),
  unit: "",
  decimals: 0,
  step: 1,
  floor: 0,
  ariaLabel: t("Fence pulses over the period"),
});
SPECIAL.trap_triggered = (t) => ({
  metric: "trap_triggered",
  label: t("Trap"),
  unit: "",
  decimals: 0,
  step: 1,
  floor: 0,
  ceiling: 1,
  words: { 0: t("open"), 1: t("closed") },
  stepped: true,
  ariaLabel: t("The trap's door over the period, closed or open"),
});
SPECIAL.movement = SPECIAL.activity;

/** The trend a status value can unfold (Tim, 2026-09-15): one of the shaped ones, else any
 * numeric metric of the registry with its label and unit; null for text, flags and values
 * the registry does not know, which stay plain. */
export function trendSpecFor(
  key: string,
  metric: Metric | undefined,
  t: Translate,
): TrendSpec | null {
  const special = SPECIAL[key];
  if (special) return special(t);
  if (!metric || metric.value_type !== "numeric") return null;
  return {
    metric: metric.key,
    label: metric.label,
    unit: metric.unit ?? "",
    ariaLabel: t("{{metric}} over the period", { metric: metric.label }),
  };
}
