import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

/**
 * The ground one proposal reads (phase 33, decision D277). A click reads a box of
 * `DEFAULT_REACH_M` to each side; a drag reads the box that was dragged. Either way the box is
 * drawn on the map before it is read, so nobody has to guess how much is being asked for, and
 * its size decides whether the read happens at all: the public Overpass answers a box of a
 * hundred square kilometres over a mapped landscape with 14 MB or with a refusal.
 */
export const DEFAULT_REACH_M = 1500;
/** Past this a box is worth a word; past `MAX_READ_KM2` it is refused. Both match the API. */
export const WARN_READ_KM2 = 9;
export const MAX_READ_KM2 = 25;
/** A drag shorter than this is a click that wobbled, not a box. */
export const DRAG_SLOP_PX = 8;

export interface ReadBox {
  west: number;
  south: number;
  east: number;
  north: number;
}

const M_PER_DEG_LAT = 110_574;
const mPerDegLon = (lat: number) => 111_320 * Math.cos((lat * Math.PI) / 180);

/** The box a click reads: the reach to each side of the point. */
export function boxAround(
  lon: number,
  lat: number,
  reachM = DEFAULT_REACH_M,
): ReadBox {
  const dlon = reachM / mPerDegLon(lat);
  const dlat = reachM / M_PER_DEG_LAT;
  return {
    west: lon - dlon,
    south: lat - dlat,
    east: lon + dlon,
    north: lat + dlat,
  };
}

/** The box a drag reads, whichever corner it started from. */
export function boxOf(a: [number, number], b: [number, number]): ReadBox {
  return {
    west: Math.min(a[0], b[0]),
    south: Math.min(a[1], b[1]),
    east: Math.max(a[0], b[0]),
    north: Math.max(a[1], b[1]),
  };
}

/** How much ground the box covers, in square kilometres. */
export function areaKm2(box: ReadBox): number {
  const midLat = (box.south + box.north) / 2;
  const width = Math.abs(box.east - box.west) * mPerDegLon(midLat);
  const height = Math.abs(box.north - box.south) * M_PER_DEG_LAT;
  return (width * height) / 1_000_000;
}

/** Whether the box may be read at all, and whether it is large enough to mention. */
export function readVerdict(box: ReadBox): {
  km2: number;
  warn: boolean;
  tooLarge: boolean;
} {
  const km2 = areaKm2(box);
  return { km2, warn: km2 > WARN_READ_KM2, tooLarge: km2 > MAX_READ_KM2 };
}

const SOURCE = "propose-box";
const LAYERS = ["propose-box-fill", "propose-box-line"];

/** The box's source and layers, once per map. */
export function ensureBoxLayer(map: MapLibreMap): void {
  if (map.getSource(SOURCE)) return;
  map.addSource(SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: "propose-box-fill",
    type: "fill",
    source: SOURCE,
    paint: {
      "fill-color": ["case", ["get", "tooLarge"], "#B91C1C", "#2563EB"],
      "fill-opacity": 0.08,
    },
  });
  map.addLayer({
    id: "propose-box-line",
    type: "line",
    source: SOURCE,
    paint: {
      "line-color": ["case", ["get", "tooLarge"], "#B91C1C", "#2563EB"],
      "line-width": 1.5,
      "line-dasharray": [3, 2],
    },
  });
}

/** Draw the box being dragged or read, or nothing. */
export function setBox(map: MapLibreMap, box: ReadBox | null): void {
  const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
  if (!source) return;
  source.setData({
    type: "FeatureCollection",
    features: box
      ? [
          {
            type: "Feature",
            properties: { tooLarge: readVerdict(box).tooLarge },
            geometry: {
              type: "Polygon",
              coordinates: [
                [
                  [box.west, box.south],
                  [box.east, box.south],
                  [box.east, box.north],
                  [box.west, box.north],
                  [box.west, box.south],
                ],
              ],
            },
          },
        ]
      : [],
  });
}

/** Take the box's layers and source off the map. */
export function removeBoxLayer(map: MapLibreMap): void {
  for (const id of LAYERS) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
}

/** What a gesture in propose mode produced. */
export interface BoxGesture {
  /** The box to read, once the gesture is finished. */
  box: ReadBox;
  /** Whether it came from a drag rather than from a plain click. */
  dragged: boolean;
}

/**
 * Propose mode's gestures on a map: a click reads the default box around the point, a drag
 * reads the box it draws. While a drag is under way the map does not pan, the box follows the
 * pointer, and letting go asks for it. A tap on a touch screen arrives as a click, which is
 * why the click handler ignores one that follows a mouse gesture it already served.
 */
export function bindBoxGestures(
  map: MapLibreMap,
  {
    reachM = DEFAULT_REACH_M,
    onPreview,
    onGesture,
  }: {
    reachM?: number;
    onPreview: (box: ReadBox | null) => void;
    onGesture: (gesture: BoxGesture) => void;
  },
): () => void {
  let from: {
    point: { x: number; y: number };
    lngLat: [number, number];
  } | null = null;
  let servedAt = 0;
  const finish = (box: ReadBox, dragged: boolean) => {
    servedAt = Date.now();
    onPreview(null);
    onGesture({ box, dragged });
  };
  const onDown = (e: {
    point: { x: number; y: number };
    lngLat: { lng: number; lat: number };
  }) => {
    from = { point: { ...e.point }, lngLat: [e.lngLat.lng, e.lngLat.lat] };
    map.dragPan.disable();
  };
  const onMove = (e: {
    point: { x: number; y: number };
    lngLat: { lng: number; lat: number };
  }) => {
    if (!from) return;
    const far = Math.hypot(e.point.x - from.point.x, e.point.y - from.point.y);
    onPreview(
      far < DRAG_SLOP_PX
        ? boxAround(from.lngLat[0], from.lngLat[1], reachM)
        : boxOf(from.lngLat, [e.lngLat.lng, e.lngLat.lat]),
    );
  };
  const onUp = (e: {
    point: { x: number; y: number };
    lngLat: { lng: number; lat: number };
  }) => {
    if (!from) return;
    const start = from;
    from = null;
    map.dragPan.enable();
    const far = Math.hypot(
      e.point.x - start.point.x,
      e.point.y - start.point.y,
    );
    finish(
      far < DRAG_SLOP_PX
        ? boxAround(start.lngLat[0], start.lngLat[1], reachM)
        : boxOf(start.lngLat, [e.lngLat.lng, e.lngLat.lat]),
      far >= DRAG_SLOP_PX,
    );
  };
  const onClick = (e: { lngLat: { lng: number; lat: number } }) => {
    // a tap; a mouse click already came through onUp a moment ago
    if (Date.now() - servedAt < 400) return;
    finish(boxAround(e.lngLat.lng, e.lngLat.lat, reachM), false);
  };
  map.on("mousedown", onDown);
  map.on("mousemove", onMove);
  map.on("mouseup", onUp);
  map.on("click", onClick);
  return () => {
    map.off("mousedown", onDown);
    map.off("mousemove", onMove);
    map.off("mouseup", onUp);
    map.off("click", onClick);
    map.dragPan.enable();
    onPreview(null);
  };
}
