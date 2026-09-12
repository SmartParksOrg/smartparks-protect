/**
 * The health dot (decision D181): what the server's status summary and the browser's own
 * reachability add up to. Deliberately slow to worry: amber comes from the server's summary
 * only (a worker silent past its window, a system alert open over 30 minutes), red only when
 * two polls in a row, a minute apart, got no answer from the server.
 */
export type DotLevel = "ok" | "degraded" | "down" | "unknown";

/** Failed polls in a row before the dot turns red; the poll runs every minute. */
export const DOWN_AFTER_FAILURES = 2;

export interface StatusSummary {
  level: string;
  reasons: string[];
  checked_at: string;
}

export function dotLevel(
  summary: StatusSummary | undefined,
  failuresInARow: number,
): DotLevel {
  if (failuresInARow >= DOWN_AFTER_FAILURES) return "down";
  if (!summary) return failuresInARow > 0 ? "ok" : "unknown";
  return summary.level === "ok" ? "ok" : "degraded";
}
