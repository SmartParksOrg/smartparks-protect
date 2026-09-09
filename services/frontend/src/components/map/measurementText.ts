import type { PointRead } from "@/api/types";

/** What one measurement reads like in the panel. */
export function measurementText(
  value: PointRead["measurements"][number],
): string {
  const v = value.value;
  const text =
    typeof v === "number"
      ? Number.isInteger(v)
        ? String(v)
        : v.toFixed(2)
      : typeof v === "boolean"
        ? v
          ? "yes"
          : "no"
        : typeof v === "string"
          ? v
          : v == null
            ? ""
            : JSON.stringify(v);
  return value.unit ? `${text} ${value.unit}` : text;
}
