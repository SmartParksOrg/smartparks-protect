import type { Gateway } from "@/api/types";

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** A Gateway Mesh relay, marked by the network sync (decision D237). */
export function isRelay(gateway: Pick<Gateway, "attributes">): boolean {
  return (
    (gateway.attributes as Record<string, unknown> | undefined)?.kind ===
    "relay"
  );
}

/** An offload station: a RangerEdge with an SD card, a gateway of the offload station source
 * and a device of ours (phase 42, decision D319). */
export function isOffloadStation(
  gateway: Pick<Gateway, "attributes">,
): boolean {
  return (
    (gateway.attributes as Record<string, unknown> | undefined)?.kind ===
    "offload_station"
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

/** A distance in words: metres under a kilometre, else kilometres with one decimal. */
export function distanceLabel(metres: number): string {
  return metres < 1000 ? `${Math.round(metres)} m` : `${(metres / 1000).toFixed(1)} km`;
}

/** The range of a gateway (decision D374): "120 m to 9.8 km, mean 2.4 km", or empty while
 * it heard nothing or has no location. */
export function rangeLabel(
  gateway: Pick<Gateway, "range_min_m" | "range_mean_m" | "range_max_m" | "range_positions">,
  t: Translate,
): string {
  if (
    !gateway.range_positions ||
    gateway.range_min_m == null ||
    gateway.range_max_m == null ||
    gateway.range_mean_m == null
  )
    return "";
  return t("{{min}} to {{max}}, mean {{mean}}", {
    min: distanceLabel(gateway.range_min_m),
    max: distanceLabel(gateway.range_max_m),
    mean: distanceLabel(gateway.range_mean_m),
  });
}
