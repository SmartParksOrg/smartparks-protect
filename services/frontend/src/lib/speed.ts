/** The speed and course a fix carries (phase 37): stored in m/s and degrees from north, read
 * as km/h and a compass point. A course at a standstill is the receiver's noise, so the
 * course text is empty unless the speed is above zero. */

const POINTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;

export function kmh(speedMps: number): number {
  return speedMps * 3.6;
}

/** "43 km/h": whole numbers, since a receiver reports whole metres per second. */
export function speedText(speedMps: number): string {
  return `${Math.round(kmh(speedMps))} km/h`;
}

/** The nearest of the eight compass points: 52° is NE, 350° is N. */
export function compassPoint(headingDeg: number): string {
  const normalised = ((headingDeg % 360) + 360) % 360;
  return POINTS[Math.round(normalised / 45) % 8];
}

/** "NE 52°" while moving, empty at a standstill or without a course. */
export function courseText(
  headingDeg: number | null | undefined,
  speedMps: number | null | undefined,
): string {
  if (headingDeg == null || speedMps == null || speedMps <= 0) return "";
  const normalised = ((headingDeg % 360) + 360) % 360;
  return `${compassPoint(normalised)} ${Math.round(normalised)}°`;
}
