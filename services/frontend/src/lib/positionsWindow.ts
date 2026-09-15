export const RECENT_DAYS = 30;

/** The window of the device and entity pages' recent positions (Tim, 2026-09-15): the 30
 * days up to the device's last known record rather than up to now, so a collar silent for a
 * year still shows its last month on its page. The anchor comes from the current state (the
 * device's last seen, the entity's position time), which leaves clock-ahead rows out; it is
 * capped at now, and without one the window ends now. */
export function lastPositionsWindow(
  anchor: string | null | undefined,
  now: number = Date.now(),
  days: number = RECENT_DAYS,
): { from: string; to: string } {
  const parsed = anchor ? Date.parse(anchor) : Number.NaN;
  // a minute past the anchor, so the record at the anchor itself is inside the window
  const end = Number.isFinite(parsed) ? Math.min(parsed + 60_000, now) : now;
  return {
    from: new Date(end - days * 86_400_000).toISOString(),
    to: new Date(end).toISOString(),
  };
}
