/** The extent of the positioned features of a project (phase 19): entities and devices
 * together, so a project whose devices have no animal yet still fits to its hardware. Pure, so
 * the map page's fit-on-switch is testable without a map. */
export type Bounds = [[number, number], [number, number]];

interface Positioned {
  geometry: { type: string; coordinates: unknown } | null | undefined;
}

export function boundsOf(features: Positioned[]): Bounds | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const f of features) {
    const g = f.geometry;
    if (!g || g.type !== "Point" || !Array.isArray(g.coordinates)) continue;
    const [lon, lat] = g.coordinates as [number, number];
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  if (west === Infinity) return null;
  return [
    [west, south],
    [east, north],
  ];
}

/** The extent of any geometries, not only points: the features of a project, so a drawing
 * map starts over the reserve rather than over a continent (Tim, 2026-09-19). */
export function geometryBounds(
  features: {
    geometry: { type: string; coordinates: unknown } | null | undefined;
  }[],
): Bounds | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  const take = (value: unknown): void => {
    if (!Array.isArray(value)) return;
    if (
      value.length >= 2 &&
      typeof value[0] === "number" &&
      typeof value[1] === "number"
    ) {
      const [lon, lat] = value as [number, number];
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
      return;
    }
    for (const inner of value) take(inner);
  };
  for (const f of features) if (f.geometry) take(f.geometry.coordinates);
  if (west === Infinity) return null;
  return [
    [west, south],
    [east, north],
  ];
}
