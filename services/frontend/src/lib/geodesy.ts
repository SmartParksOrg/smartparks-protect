/** Distances and areas on the sphere for the map's measuring tool (decisions D139, D171): a
 * haversine for lengths and the spherical excess formula for polygon areas, both on the mean
 * earth radius, plus the centre of a drawn circle (D172) and the ring of a radius (the circle
 * feature and the Locate accuracy ring, D173). Coordinates are [longitude, latitude] in
 * degrees, as GeoJSON has them. */

export const EARTH_RADIUS_M = 6_371_008.8;

const rad = (deg: number) => (deg * Math.PI) / 180;

/** Great-circle distance in metres between two points. */
export function distanceMetres(
  a: [number, number],
  b: [number, number],
): number {
  const [lon1, lat1] = [rad(a[0]), rad(a[1])];
  const [lon2, lat2] = [rad(b[0]), rad(b[1])];
  const h =
    Math.sin((lat2 - lat1) / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

/** The length of a line in metres, vertex to vertex. */
export function lengthMetres(coordinates: [number, number][]): number {
  let total = 0;
  for (let i = 1; i < coordinates.length; i += 1)
    total += distanceMetres(coordinates[i - 1], coordinates[i]);
  return total;
}

/** The area of a ring in square metres on the sphere (Chamberlain and Duquette, "Some
 * algorithms for polygons on a sphere", JPL 2007): exact for polygons small against the
 * earth, which every geofence is. The ring may be open or closed; holes are not handled. */
export function ringAreaSquareMetres(ring: [number, number][]): number {
  const points =
    ring.length > 1 && sameCoordinate(ring[0], ring[ring.length - 1])
      ? ring.slice(0, -1)
      : ring;
  if (points.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < points.length; i += 1) {
    const p1 = points[i];
    const p2 = points[(i + 1) % points.length];
    sum +=
      (rad(p2[0]) - rad(p1[0])) *
      (2 + Math.sin(rad(p1[1])) + Math.sin(rad(p2[1])));
  }
  return Math.abs((sum * EARTH_RADIUS_M * EARTH_RADIUS_M) / 2);
}

const sameCoordinate = (a: [number, number], b: [number, number]) =>
  a[0] === b[0] && a[1] === b[1];

/** The perimeter of a ring in metres, closed. */
export function perimeterMetres(ring: [number, number][]): number {
  if (ring.length < 2) return 0;
  const closed = sameCoordinate(ring[0], ring[ring.length - 1])
    ? ring
    : [...ring, ring[0]];
  return lengthMetres(closed);
}

/** A length as a person reads it: metres under a kilometre, else kilometres. */
export function formatLength(metres: number): string {
  if (metres < 1000) return `${Math.round(metres)} m`;
  return `${(metres / 1000).toFixed(metres < 10_000 ? 2 : 1)} km`;
}

/** An area as a person reads it: square metres under a hectare, hectares under a square
 * kilometre, else square kilometres. */
export function formatArea(squareMetres: number): string {
  if (squareMetres < 10_000) return `${Math.round(squareMetres)} m²`;
  if (squareMetres < 1_000_000)
    return `${(squareMetres / 10_000).toFixed(2)} ha`;
  return `${(squareMetres / 1_000_000).toFixed(2)} km²`;
}

/** What a geometry measures: a line its length, a polygon its area and perimeter. */
export function measure(geometry: GeoJSON.Geometry | null): {
  length_m?: number;
  area_m2?: number;
} {
  if (!geometry) return {};
  if (geometry.type === "LineString")
    return {
      length_m: lengthMetres(geometry.coordinates as [number, number][]),
    };
  if (geometry.type === "Polygon") {
    const ring = (geometry.coordinates[0] ?? []) as [number, number][];
    return {
      area_m2: ringAreaSquareMetres(ring),
      length_m: perimeterMetres(ring),
    };
  }
  return {};
}

/** The centre of a ring as the mean of its vertices (the last one repeats the first). */
export function polygonCentre(ring: [number, number][]): [number, number] {
  const points = ring.length > 1 ? ring.slice(0, -1) : ring;
  const n = Math.max(points.length, 1);
  return [
    points.reduce((sum, [lon]) => sum + lon, 0) / n,
    points.reduce((sum, [, lat]) => sum + lat, 0) / n,
  ];
}

/** A circle on the sphere as a closed ring of `segments` points, for accuracy rings and circle
 * features (decision D172). */
export function circleRing(
  centre: [number, number],
  radiusMetres: number,
  segments = 64,
): [number, number][] {
  const [lon, lat] = centre;
  const latR = (lat * Math.PI) / 180;
  const lonR = (lon * Math.PI) / 180;
  const d = radiusMetres / EARTH_RADIUS_M;
  const ring: [number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const bearing = (2 * Math.PI * (i % segments)) / segments;
    const lat2 = Math.asin(
      Math.sin(latR) * Math.cos(d) + Math.cos(latR) * Math.sin(d) * Math.cos(bearing),
    );
    const lon2 =
      lonR +
      Math.atan2(
        Math.sin(bearing) * Math.sin(d) * Math.cos(latR),
        Math.cos(d) - Math.sin(latR) * Math.sin(lat2),
      );
    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return ring;
}

