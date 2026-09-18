import type { Gateway } from "@/api/types";

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** A Gateway Mesh relay, marked by the network sync (decision D237). */
export function isRelay(gateway: Pick<Gateway, "attributes">): boolean {
  return (
    (gateway.attributes as Record<string, unknown> | undefined)?.kind ===
    "relay"
  );
}

/** Where a gateway's location came from, in words: the raw key is a column value, not a
 * label (Tim, 2026-09-18: the live map's panel showed "(admin)"). */
export function locationSourceLabel(source: string, t: Translate): string {
  if (source === "admin") return t("an administrator");
  if (source === "reception") return t("the coordinates on an uplink");
  return t("the platform's gateway list");
}

/** "latitude, longitude" of a gateway to the given decimals, empty when it has none. */
export function gatewayCoords(
  gateway: Pick<Gateway, "geometry">,
  decimals = 4,
): string {
  const c = (gateway.geometry as { coordinates?: number[] } | null)
    ?.coordinates;
  return c && c.length >= 2
    ? `${c[1].toFixed(decimals)}, ${c[0].toFixed(decimals)}`
    : "";
}
