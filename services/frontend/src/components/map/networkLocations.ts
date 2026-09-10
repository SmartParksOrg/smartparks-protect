/** Network locations on the map (decisions D162 and D163): where a network placed a device (an
 * Iridium estimate, a LoRaWAN geolocation), drawn as a circle of its radius in metres, so the
 * circle keeps its size on the ground at every zoom. Never a device's own fix. */

const EARTH_RADIUS_M = 6_371_008.8;
const SEGMENTS = 48;

export interface NetworkLocationProperties {
  position_id: number;
  time: string;
  accuracy_m: number | null;
  method: string | null;
  device_id: string;
  device_name: string;
  entity_id: string | null;
  entity_name: string | null;
  source_event_id: number | null;
}

/** A polygon approximating the circle of `radiusM` metres around a point, as GeoJSON. */
export function circlePolygon(
  latitude: number,
  longitude: number,
  radiusM: number,
): GeoJSON.Polygon {
  const lat = (latitude * Math.PI) / 180;
  const lon = (longitude * Math.PI) / 180;
  const d = radiusM / EARTH_RADIUS_M;
  const ring: [number, number][] = [];
  for (let i = 0; i <= SEGMENTS; i += 1) {
    const bearing = (2 * Math.PI * i) / SEGMENTS;
    const lat2 = Math.asin(
      Math.sin(lat) * Math.cos(d) +
        Math.cos(lat) * Math.sin(d) * Math.cos(bearing),
    );
    const lon2 =
      lon +
      Math.atan2(
        Math.sin(bearing) * Math.sin(d) * Math.cos(lat),
        Math.cos(d) - Math.sin(lat) * Math.sin(lat2),
      );
    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return { type: "Polygon", coordinates: [ring] };
}

/** The location points of the API as circle polygons plus their centres, so the map draws the
 * radius and a dot the person can read; at least half a kilometre so a point stays visible. */
export function locationFeatures(points: GeoJSON.Feature[]): GeoJSON.Feature[] {
  const out: GeoJSON.Feature[] = [];
  for (const point of points) {
    if (point.geometry.type !== "Point") continue;
    const [lon, lat] = point.geometry.coordinates;
    const props = (point.properties ??
      {}) as Partial<NetworkLocationProperties>;
    const radiusM = Math.max(500, props.accuracy_m ?? 0);
    out.push({
      type: "Feature",
      id: point.id,
      geometry: circlePolygon(lat, lon, radiusM),
      properties: { ...props, kind: "circle" },
    });
    out.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: { ...props, kind: "centre" },
    });
  }
  return out;
}
