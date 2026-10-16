import type { TFunction } from "i18next";

import { t as mark } from "@/lib/i18nMark";

/** The windows the traffic and trace pages look back over, in hours. The API caps nothing but
 * the rows (the newest 200), so the presets run to what is kept: source events two years,
 * failed traces 180 days, routine traces 30 days (Tim, 2026-10-16: the old field stopped at
 * 720 hours for no reason the server knew). */
export const WINDOW_PRESETS: ReadonlyArray<{ hours: number; label: string }> = [
  { hours: 1, label: mark("Last hour") },
  { hours: 6, label: mark("Last 6 hours") },
  { hours: 24, label: mark("Last 24 hours") },
  { hours: 72, label: mark("Last 3 days") },
  { hours: 168, label: mark("Last 7 days") },
  { hours: 720, label: mark("Last 30 days") },
  { hours: 24 * 90, label: mark("Last 90 days") },
  { hours: 24 * 365, label: mark("Last year") },
  { hours: 24 * 730, label: mark("Last 2 years") },
];

/** The rows a traffic or trace list asks for: the newest this many in the window. */
export const WINDOW_ROWS = 200;

/** The footer under a list: how many rows, and that they are the newest when the window held
 * more than the list shows. */
export function windowFooter(count: number, hours: number, t: TFunction): string {
  const window = windowLabel(hours, t).toLowerCase();
  return count >= WINDOW_ROWS
    ? t("the newest {{count}} messages, {{window}}", { count, window })
    : t("{{count}} messages, {{window}}", { count, window });
}

/** "Last 7 days" for a preset, "Last 36 hours" for a window a link carried. */
export function windowLabel(hours: number, t: TFunction): string {
  const preset = WINDOW_PRESETS.find((p) => p.hours === hours);
  return preset ? t(preset.label) : t("Last {{count}} hours", { count: hours });
}
