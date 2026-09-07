import type { Position } from "@/api/types";

export interface MiniMapGeometry {
  /** The trail, oldest first, as [lon, lat] pairs. */
  line: [number, number][];
  /** The newest position. */
  latest: [number, number];
  /** [west, south, east, north] of every position. */
  bounds: [number, number, number, number];
}

const coordinatesOf = (p: Position): [number, number] | null => {
  const c = (p.geometry as { coordinates?: unknown } | null)?.coordinates;
  return Array.isArray(c) &&
    c.length >= 2 &&
    typeof c[0] === "number" &&
    typeof c[1] === "number"
    ? [c[0], c[1]]
    : null;
};

/** The trail and the extent of the positions the API returns newest first (decision D124);
 * null when none has coordinates. */
export function miniMapGeometry(positions: Position[]): MiniMapGeometry | null {
  const points = positions
    .map(coordinatesOf)
    .filter((c): c is [number, number] => c !== null);
  if (points.length === 0) return null;
  const line = [...points].reverse();
  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  return {
    line,
    latest: points[0],
    bounds: [
      Math.min(...lons),
      Math.min(...lats),
      Math.max(...lons),
      Math.max(...lats),
    ],
  };
}
