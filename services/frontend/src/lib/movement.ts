/** Movement from a collar's accelerometer (Tim, 2026-09-14), read the way the backend's
 * health line reads it (shared/domain/movement.py): the change of the acceleration vector
 * between two status messages is the `activity` metric, and the last change above the
 * threshold is the device's `last_movement_at`. Still for 12 hours warns, 24 is critical. */
export const STILL_WARN_HOURS = 12;
export const STILL_CRITICAL_HOURS = 24;

export type MovementLevel = "ok" | "warn" | "critical" | null;

export function movementLevel(
  lastMovementAt: string | null | undefined,
  now: number,
): MovementLevel {
  if (!lastMovementAt) return null;
  const hours = (now - Date.parse(lastMovementAt)) / 3_600_000;
  if (hours >= STILL_CRITICAL_HOURS) return "critical";
  if (hours >= STILL_WARN_HOURS) return "warn";
  return "ok";
}

/** Whole hours a collar has been still, or null while it is moving or unknown. */
export function stillHours(
  lastMovementAt: string | null | undefined,
  now: number,
): number | null {
  const level = movementLevel(lastMovementAt, now);
  if (level === null || level === "ok") return null;
  return Math.floor((now - Date.parse(lastMovementAt as string)) / 3_600_000);
}
