/** Whether and why the server is out of reach (decision D329, Tim, 2026-10-16: a deploy on
 * dev showed every user a bare 502). Pure; the store and the client apply it. */

export type UnavailableReason = "updating" | "unreachable";

/** The statuses nginx or a proxy answer while an upstream is down or restarting. */
export function isUnavailableStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

/** "updating" for a 503, which nginx answers while the deploy's flag is up (and a maintenance
 * page anywhere else means much the same); "unreachable" for a 502 or 504, which is an
 * upstream nobody raised a flag for, and for a failed connection. */
export function reasonOf(status: number, detail: unknown): UnavailableReason {
  void detail;
  return status === 503 ? "updating" : "unreachable";
}
