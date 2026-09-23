import { t } from "@/lib/i18nMark";

/** The registry's categories in the order a reader of an animal wants them: the animal first,
 * where it is, what is around it, then the hardware (Tim, 2026-09-23). A category the list does
 * not know goes last, before the keys nobody has categorised yet. */
const CATEGORY_ORDER = [
  "physiology",
  "behaviour",
  "movement",
  "positioning",
  "environment",
  "infrastructure",
  "connectivity",
  "device_health",
];
export const CATEGORY_LABELS: Record<string, string> = {
  physiology: t("Physiology"),
  behaviour: t("Behaviour"),
  movement: t("Movement"),
  positioning: t("Positioning"),
  environment: t("Environment"),
  infrastructure: t("Infrastructure"),
  connectivity: t("Connectivity"),
  device_health: t("Device health"),
  uncategorized: t("Not categorised yet"),
};

/** The metrics grouped by category, in `CATEGORY_ORDER`, sorted by label within a group. */
export function groupMetrics<T extends { metric_key: string; label: string }>(
  items: T[],
  categoryOf: (key: string) => string | undefined,
): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const category = categoryOf(item.metric_key) ?? "uncategorized";
    groups.set(category, [...(groups.get(category) ?? []), item]);
  }
  const rank = (category: string) => {
    const index = CATEGORY_ORDER.indexOf(category);
    if (index >= 0) return index;
    return category === "uncategorized"
      ? CATEGORY_ORDER.length + 1
      : CATEGORY_ORDER.length;
  };
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([category, rows]) => [
      category,
      [...rows].sort((a, b) => a.label.localeCompare(b.label)),
    ]);
}
