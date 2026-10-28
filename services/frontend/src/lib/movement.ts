/** Movement from a device's accelerometer (Tim, 2026-09-14) and from its fixes (decision
 * D363), read the way the backend's health line reads it (shared/domain/movement.py): the
 * change of the acceleration vector between two status messages is the `activity` metric and
 * the last change above the threshold is the device's `last_movement_at`; a valid fix beyond
 * the jitter bar from the one before it is `last_fix_movement_at`. The newer of the two is the
 * movement shown, with its source named. Still for 12 hours warns, 24 is critical. */
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

/** Whole hours a device has been still, or null while it is moving or unknown. */
export function stillHours(
  lastMovementAt: string | null | undefined,
  now: number,
): number | null {
  const level = movementLevel(lastMovementAt, now);
  if (level === null || level === "ok") return null;
  return Math.floor((now - Date.parse(lastMovementAt as string)) / 3_600_000);
}

export type MovementSource = "positions" | "accelerometer";

/** The newer movement of the two sources and which one saw it; the fixes' word when both
 * name the same moment. */
export function lastMovement(
  accelerometerAt: string | null | undefined,
  fixAt: string | null | undefined,
): { at: string | null; source: MovementSource | null } {
  if (fixAt && (!accelerometerAt || Date.parse(fixAt) >= Date.parse(accelerometerAt))) {
    return { at: fixAt, source: "positions" };
  }
  if (accelerometerAt) return { at: accelerometerAt, source: "accelerometer" };
  return { at: null, source: null };
}
