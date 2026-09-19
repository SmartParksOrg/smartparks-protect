import type { Feature } from "@/api/types";

/** A fence line's level and its colour on the map (phase 32, decision D264): the marker
 * palette's green, amber, red and grey, so a fence reads like everything else. */
export const FENCE_LEVELS = ["ok", "low", "down", "unknown"] as const;
export type FenceLevel = (typeof FENCE_LEVELS)[number];
export const FENCE_COLORS: Record<FenceLevel, string> = {
  ok: "#52735E",
  low: "#C6B187",
  down: "#A13D2D",
  unknown: "#8A9590",
};

export function fenceColor(level: string | null | undefined): string {
  return (
    FENCE_COLORS[(level ?? "unknown") as FenceLevel] ?? FENCE_COLORS.unknown
  );
}

/** The words for a fence level, as a person reads a fence. */
export function fenceLevelLabel(
  level: string | null | undefined,
  t: (key: string) => string,
): string {
  switch (level) {
    case "ok":
      return t("live");
    case "low":
      return t("low");
    case "down":
      return t("down");
    default:
      return t("unknown");
  }
}

/** A section of a fence line and a monitor on it, as the fence status carries them. */
export interface FenceSection {
  from_m: number;
  to_m: number;
  level: string;
  monitor_ids?: string[];
}
export interface FenceMonitor {
  entity_id: string;
  name: string;
  device_id?: string | null;
  position_m?: number | null;
  voltage_v?: number | null;
  pulses?: number | null;
  measured_at?: string | null;
  failed?: boolean;
  level: string;
}

export function kilovolts(voltageV: number | null | undefined): string {
  return voltageV == null ? "–" : `${(voltageV / 1000).toFixed(2)} kV`;
}

const EARTH_RADIUS_M = 6_371_008.8;

/** The line's vertices in metres on a flat frame around its middle: the same frame the server
 * cuts the sections on, so a section's metres land on the same stretch here. */
function flat(coordinates: number[][]): [number, number][] {
  const lat0 =
    (coordinates.reduce((sum, c) => sum + c[1], 0) / coordinates.length) *
    (Math.PI / 180);
  const lon0 =
    coordinates.reduce((sum, c) => sum + c[0], 0) / coordinates.length;
  const scaleX = EARTH_RADIUS_M * Math.cos(lat0) * (Math.PI / 180);
  const scaleY = EARTH_RADIUS_M * (Math.PI / 180);
  return coordinates.map((c) => [
    (c[0] - lon0) * scaleX,
    (c[1] - lat0 * (180 / Math.PI)) * scaleY,
  ]);
}

/** The part of a line between two distances from its start, in degrees, for drawing one
 * section in its own colour. */
export function sliceLine(
  coordinates: number[][],
  fromM: number,
  toM: number,
): number[][] {
  const metres = flat(coordinates);
  const out: number[][] = [];
  let walked = 0;
  const at = (i: number, t: number): number[] => [
    coordinates[i][0] + t * (coordinates[i + 1][0] - coordinates[i][0]),
    coordinates[i][1] + t * (coordinates[i + 1][1] - coordinates[i][1]),
  ];
  for (let i = 0; i < metres.length - 1; i += 1) {
    const step = Math.hypot(
      metres[i + 1][0] - metres[i][0],
      metres[i + 1][1] - metres[i][1],
    );
    const start = walked;
    const end = walked + step;
    if (step > 0 && end >= fromM && start <= toM) {
      const t0 = Math.max(0, (fromM - start) / step);
      const t1 = Math.min(1, (toM - start) / step);
      if (out.length === 0) out.push(at(i, t0));
      out.push(at(i, t1));
    }
    walked = end;
  }
  if (out.length < 2) return coordinates;
  return out;
}

/** A fence line as one map feature per section, each carrying its level; any other feature,
 * or a fence without sections, as itself. */
export function fenceSectionFeatures(feature: Feature): GeoJSON.Feature[] {
  const geometry = feature.geometry as unknown as GeoJSON.Geometry | null;
  const base = {
    id: feature.id,
    name: feature.name,
    feature_type: feature.feature_type,
  };
  if (!geometry) return [];
  const sections = feature.fence_sections ?? null;
  if (
    feature.feature_type !== "fence" ||
    geometry.type !== "LineString" ||
    !sections ||
    sections.length === 0
  ) {
    return [
      {
        type: "Feature",
        geometry,
        properties: { ...base, fence_level: feature.fence_level ?? undefined },
      },
    ];
  }
  return sections.map((section, index) => ({
    type: "Feature",
    geometry: {
      type: "LineString",
      coordinates: sliceLine(
        geometry.coordinates as number[][],
        Number(section.from_m),
        Number(section.to_m),
      ),
    },
    properties: {
      ...base,
      fence_level: String(section.level ?? "unknown"),
      section: index,
    },
  }));
}
