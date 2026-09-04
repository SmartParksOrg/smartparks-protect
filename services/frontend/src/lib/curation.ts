/** Labels and formatting for data curation (architecture 28). */
import { formatTime } from "@/lib/format";

/** A canonical record to curate: type, id and its original time (the key of the row). */
export interface CurationTarget { target_type: "position" | "measurement"; target_id: number; target_time: string }

export const FIELD_LABELS: Record<string, string> = { time: "time", coordinates: "coordinates", value: "value", valid: "validity" };
export const REASON_LABELS: Record<string, string> = {
  DEVICE_FIRMWARE_BUG: "device firmware bug",
  DEVICE_CLOCK_ERROR: "device clock error",
  TIMEZONE_ERROR: "timezone error",
  GPS_OUTLIER: "GPS outlier",
  CALIBRATION_ERROR: "calibration error",
  WRONG_ENTITY_ASSIGNMENT: "wrong entity assignment",
  WRONG_PROJECT_ASSIGNMENT: "wrong project assignment",
  CLASSIFICATION_CORRECTION: "classification correction",
  MANUAL_QC: "manual quality control",
  OTHER: "other",
};

export function formatValue(field: string, value: unknown): string {
  if (value === null || value === undefined) return "none";
  if (field === "time") return formatTime(String(value));
  if (field === "coordinates" && typeof value === "object") { const v = value as { latitude: number; longitude: number }; return `${v.latitude.toFixed(6)}, ${v.longitude.toFixed(6)}`; }
  if (typeof value === "boolean") return value ? "valid" : "invalid";
  return String(value);
}

/** An ISO instant as the value of a `datetime-local` input with seconds, in the browser's zone. */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
