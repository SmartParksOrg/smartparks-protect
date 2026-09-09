import { clampHours, DEFAULT_TRACK_HOURS } from "@/components/map/trackLength";

/** The heatmap's settings (decision D138): a radius in metres, a sensitivity from low to high
 * and a look-back in hours, carried in the URL and kept per user as the default. A heatmap is
 * switched on per entity and device like a track (`?heat=` and `?device_heat=` list them), and
 * one setting applies to every heatmap on the map. */
export interface HeatSettings {
  radius_m: number;
  /** 1 (low) to 5 (high). */
  sensitivity: number;
  hours: number;
}

export const HEAT_MIN_RADIUS_M = 10;
export const HEAT_MAX_RADIUS_M = 5000;
export const HEAT_MIN_SENSITIVITY = 1;
export const HEAT_MAX_SENSITIVITY = 5;
export const DEFAULT_HEAT: HeatSettings = {
  radius_m: 250,
  sensitivity: 3,
  hours: DEFAULT_TRACK_HOURS,
};
/** The largest radius drawn, in pixels; beyond it the blur costs more than it shows. The
 * smallest keeps a spot visible zoomed out, where a few hundred metres are under a pixel. */
const MAX_RADIUS_PX = 200;
const MIN_RADIUS_PX = 6;

export function clampRadius(metres: number): number {
  if (!Number.isFinite(metres)) return DEFAULT_HEAT.radius_m;
  return Math.min(
    HEAT_MAX_RADIUS_M,
    Math.max(HEAT_MIN_RADIUS_M, Math.round(metres)),
  );
}

export function clampSensitivity(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_HEAT.sensitivity;
  return Math.min(
    HEAT_MAX_SENSITIVITY,
    Math.max(HEAT_MIN_SENSITIVITY, Math.round(value)),
  );
}

/** The settings from `heat_radius=`, `heat_sensitivity=` and `heat_hours=`, the defaults for
 * what is missing. */
export function parseHeatSettings(
  params: URLSearchParams,
  defaults: HeatSettings,
): HeatSettings {
  const radius = params.get("heat_radius");
  const sensitivity = params.get("heat_sensitivity");
  const hours = params.get("heat_hours");
  return {
    radius_m: radius ? clampRadius(Number(radius)) : defaults.radius_m,
    sensitivity: sensitivity
      ? clampSensitivity(Number(sensitivity))
      : defaults.sensitivity,
    hours: hours ? clampHours(Number(hours)) : defaults.hours,
  };
}

/** Metres per pixel of Web Mercator at a latitude and zoom. */
export function metresPerPixel(latitude: number, zoom: number): number {
  return (156543.03392 * Math.cos((latitude * Math.PI) / 180)) / 2 ** zoom;
}

/** The `heatmap-radius` expression: the radius in metres turned into pixels per zoom at the
 * map's latitude, as interpolation stops from zoom 0 to 22, clamped so the blur stays sane. */
export function radiusExpression(
  radiusMetres: number,
  latitude: number,
): ["interpolate", ["exponential", number], ["zoom"], ...number[]] {
  const stops: number[] = [];
  for (let zoom = 0; zoom <= 22; zoom += 1) {
    const px = radiusMetres / metresPerPixel(latitude, zoom);
    stops.push(zoom, Math.min(MAX_RADIUS_PX, Math.max(MIN_RADIUS_PX, px)));
  }
  return ["interpolate", ["exponential", 2], ["zoom"], ...stops];
}

/** Sensitivity to the layer's intensity: low means a spot needs many points to glow, high
 * means a few do. */
export function intensityFor(sensitivity: number): number {
  return [0.3, 0.6, 1, 1.8, 3][clampSensitivity(sensitivity) - 1];
}

export function sensitivityLabel(sensitivity: number): string {
  return ["Low", "Lower", "Medium", "Higher", "High"][
    clampSensitivity(sensitivity) - 1
  ];
}
