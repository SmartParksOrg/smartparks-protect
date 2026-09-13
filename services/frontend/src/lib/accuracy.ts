/** When a position's accuracy is worth a warning (decision D193): a radius known and above
 * this many metres draws an accuracy circle on the map and a note in the panels, whether the
 * position is a network estimate or a device fix taken under a poor sky. */
export const ACCURACY_WARN_M = 50;

export function imprecise(accuracyM: number | null | undefined): boolean {
  return (
    accuracyM != null &&
    Number.isFinite(accuracyM) &&
    accuracyM > ACCURACY_WARN_M
  );
}
