/** The length of the tracks on the live map (decision D109). One length applies to every track:
 * a number of hours, or "assigned" for the time since the device tracking the entity was
 * assigned to it. The URL carries it as `track=`; the last choice is kept per user. */

export type TrackLength = number | "assigned";

export const TRACK_MIN_HOURS = 1;
export const TRACK_MAX_DAYS = 90;
export const TRACK_MAX_HOURS = TRACK_MAX_DAYS * 24;
export const DEFAULT_TRACK_HOURS = 24;
/** The quick picks in the settings, in hours. */
export const TRACK_QUICK_PICKS = [6, 24, 7 * 24, 30 * 24];

export function clampHours(hours: number): number {
  if (!Number.isFinite(hours)) return DEFAULT_TRACK_HOURS;
  return Math.min(TRACK_MAX_HOURS, Math.max(TRACK_MIN_HOURS, Math.round(hours)));
}

/** `track=` from the URL: a number of hours, "assigned", or nothing (the fallback). */
export function parseTrackLength(value: string | null, fallback: TrackLength): TrackLength {
  if (value === "assigned") return "assigned";
  const hours = Number(value);
  return value && hours > 0 ? clampHours(hours) : fallback;
}

export function trackLengthParam(length: TrackLength): string {
  return length === "assigned" ? "assigned" : String(length);
}

/** Hours as the unit a person would say: whole days from a day up, else hours. */
export function describeHours(hours: number): { value: number; unit: "hours" | "days" } {
  if (hours >= 24 && hours % 24 === 0) return { value: hours / 24, unit: "days" };
  return { value: hours, unit: "hours" };
}

/** The start of one entity's track. With "assigned" and no assignment the fallback hours
 * apply, so an entity without a device still gets a track. */
export function trackFrom(
  length: TrackLength,
  assignedSince: string | null | undefined,
  fallbackHours: number,
  now: number = Date.now(),
): string {
  if (length === "assigned" && assignedSince) return assignedSince;
  const hours = length === "assigned" ? fallbackHours : length;
  return new Date(now - hours * 3600_000).toISOString();
}
