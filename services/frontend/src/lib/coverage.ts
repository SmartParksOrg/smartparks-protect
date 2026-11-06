/** The periods the coverage layer and a gateway's Coverage tab offer, in hours. */
export const COVERAGE_PERIODS = [24, 72, 168, 720, 2160];

export function periodLabel(
  hours: number,
  t: (key: string, o?: Record<string, unknown>) => string,
): string {
  return hours < 48
    ? t("{{count}} hours", { count: hours })
    : t("{{count}} days", { count: Math.round(hours / 24) });
}
