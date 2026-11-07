import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

import { DURATION, easeOut } from "@/lib/motion";

/**
 * The live map's motion on a new position (decision D380): the marker glides from the spot it
 * had to the new one, and a ring in the brand green expands once from the new spot and fades.
 * Both follow a position from the WebSocket alone; a refetch or a page load moves nothing, and
 * no frame is drawn while no glide or ring is under way. The caller leaves both out under
 * reduce motion.
 */

export type LngLat = [number, number];

interface Glide {
  from: LngLat;
  to: LngLat;
  start: number;
}

interface Ring {
  at: LngLat;
  start: number;
}

export const PULSE_SOURCE = "live-pulse";
export const PULSE_LAYER = "live-pulse";

const glides = new Map<string, Glide>();
const rings: Ring[] = [];
const listeners = new Set<() => void>();
let frame = 0;
let pulseMap: MapLibreMap | null = null;

/** The key of a glide: the entity's or the device's marker. */
export function glideKey(kind: "entity" | "device", id: string): string {
  return `${kind}:${id}`;
}

/** Where a marker is on its way: between `from` and `to` by the time passed, `to` once there. */
export function glidedCoordinates(
  key: string,
  to: LngLat,
  now: number,
): LngLat {
  const glide = glides.get(key);
  if (!glide) return to;
  const t = (now - glide.start) / DURATION.glide;
  if (t >= 1) return to;
  const k = easeOut(t);
  return [
    glide.from[0] + (glide.to[0] - glide.from[0]) * k,
    glide.from[1] + (glide.to[1] - glide.from[1]) * k,
  ];
}

/** Starts a marker's glide from `from` to `to`; a marker already on its way starts again from
 * where it is now. Nothing starts when the two spots are the same. */
export function startGlide(
  key: string,
  from: LngLat,
  to: LngLat,
  now = performance.now(),
): void {
  if (from[0] === to[0] && from[1] === to[1]) return;
  glides.set(key, { from: glidedCoordinates(key, from, now), to, start: now });
  run();
}

/** A ring that expands once from `at` and fades (the map must have the pulse layer). */
export function pulseAt(
  map: MapLibreMap,
  at: LngLat,
  now = performance.now(),
): void {
  pulseMap = map;
  rings.push({ at, start: now });
  run();
}

/** Called on every frame while something is under way, and once more when the last glide
 * ended, so the markers land on their final spot. */
export function onMotionFrame(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The ring's source and layer: a circle whose radius grows and whose stroke fades with the
 * ring's `age` from 0 to 1, above every marker. */
export function ensurePulseLayer(map: MapLibreMap): void {
  if (map.getSource(PULSE_SOURCE)) return;
  map.addSource(PULSE_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: PULSE_LAYER,
    type: "circle",
    source: PULSE_SOURCE,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "age"], 0, 8, 1, 40],
      "circle-color": "transparent",
      "circle-stroke-width": 2,
      "circle-stroke-color": "#52735E",
      "circle-stroke-opacity": [
        "interpolate",
        ["linear"],
        ["get", "age"],
        0,
        0.8,
        1,
        0,
      ],
    },
  });
}

/** Whether a glide or a ring is under way (for the tests). */
export function inMotion(): boolean {
  return glides.size > 0 || rings.length > 0;
}

/** Forgets every glide and ring (for the tests). */
export function resetMotion(): void {
  glides.clear();
  rings.length = 0;
  if (frame) cancelAnimationFrame(frame);
  frame = 0;
}

function run(): void {
  if (frame) return;
  frame = requestAnimationFrame(tick);
}

function tick(now: number): void {
  frame = 0;
  const gliding = glides.size > 0;
  // a glide that ended is forgotten first, so the redraw lands its marker on the new spot
  for (const [key, glide] of glides) {
    if (now - glide.start >= DURATION.glide) glides.delete(key);
  }
  if (gliding) for (const listener of listeners) listener();
  drawRings(now);
  if (glides.size > 0 || rings.length > 0) run();
}

function drawRings(now: number): void {
  if (!pulseMap) return;
  const source = pulseMap.getSource(PULSE_SOURCE) as GeoJSONSource | undefined;
  if (!source) return;
  for (let i = rings.length - 1; i >= 0; i--) {
    if (now - rings[i].start >= DURATION.ring) rings.splice(i, 1);
  }
  source.setData({
    type: "FeatureCollection",
    features: rings.map((ring) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: ring.at },
      properties: { age: easeOut((now - ring.start) / DURATION.ring) },
    })),
  });
}
