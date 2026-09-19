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

/** Consecutive sections of one level, as a person names a stretch: "Middle to South corner". */
export interface FenceRun {
  level: string;
  from_m: number;
  to_m: number;
  monitor_ids: string[];
}

export function fenceRuns(sections: FenceSection[]): FenceRun[] {
  const runs: FenceRun[] = [];
  for (const s of sections) {
    const last = runs[runs.length - 1];
    if (last && last.level === s.level && last.to_m === s.from_m) {
      last.to_m = s.to_m;
      for (const id of s.monitor_ids ?? [])
        if (!last.monitor_ids.includes(id)) last.monitor_ids.push(id);
    } else {
      runs.push({
        level: s.level,
        from_m: s.from_m,
        to_m: s.to_m,
        monitor_ids: [...(s.monitor_ids ?? [])],
      });
    }
  }
  return runs;
}

/** The one sentence a panel needs (Tim, 2026-09-19): what is wrong and where, or that all is
 * well. "2 of 4 sections down, Middle to South corner"; "all 4 sections live"; "no monitor". */
export function fenceSummary(
  sections: FenceSection[],
  monitors: FenceMonitor[],
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (monitors.length === 0) return t("No fence monitor on this line yet.");
  const total = sections.length;
  const name = (id: string) =>
    monitors.find((m) => m.entity_id === id)?.name ?? "?";
  const where = (run: FenceRun): string => {
    const names = run.monitor_ids.map(name);
    if (names.length === 0) return "";
    if (names.length === 1) return names[0];
    return t("{{from}} to {{to}}", {
      from: names[0],
      to: names[names.length - 1],
    });
  };
  const runs = fenceRuns(sections);
  for (const level of ["down", "unknown", "low"] as const) {
    const bad = runs.filter((r) => r.level === level);
    if (bad.length === 0) continue;
    const count = sections.filter((s) => s.level === level).length;
    const places = bad.map(where).filter(Boolean).join("; ");
    // three plain calls rather than one with a chosen key, so the catalogue sees each
    const head =
      level === "down"
        ? t("{{count}} of {{total}} sections down", { count, total })
        : level === "unknown"
          ? t("{{count}} of {{total}} sections unknown", { count, total })
          : t("{{count}} of {{total}} sections low", { count, total });
    return places ? `${head}, ${places}` : head;
  }
  return t("all {{count}} sections live", { count: total });
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

/** The point of the line nearest to a place, and how far along the line it is: where a
 * monitor dropped near the line goes, shown at once while the server does the same. */
export function nearestOnLine(
  coordinates: number[][],
  lon: number,
  lat: number,
): { lon: number; lat: number; metres: number } {
  const metres = flat(coordinates);
  const lat0 =
    (coordinates.reduce((s, c) => s + c[1], 0) / coordinates.length) *
    (Math.PI / 180);
  const lon0 = coordinates.reduce((s, c) => s + c[0], 0) / coordinates.length;
  const px = (lon - lon0) * EARTH_RADIUS_M * Math.cos(lat0) * (Math.PI / 180);
  const py = (lat - lat0 * (180 / Math.PI)) * EARTH_RADIUS_M * (Math.PI / 180);
  let best = Infinity;
  let at = { lon: coordinates[0][0], lat: coordinates[0][1], metres: 0 };
  let walked = 0;
  for (let i = 0; i < metres.length - 1; i += 1) {
    const [ax, ay] = metres[i];
    const [bx, by] = metres[i + 1];
    const dx = bx - ax;
    const dy = by - ay;
    const length2 = dx * dx + dy * dy;
    const t =
      length2 === 0
        ? 0
        : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / length2));
    const cx = ax + t * dx;
    const cy = ay + t * dy;
    const d2 = (px - cx) ** 2 + (py - cy) ** 2;
    if (d2 < best) {
      best = d2;
      at = {
        lon:
          coordinates[i][0] + t * (coordinates[i + 1][0] - coordinates[i][0]),
        lat:
          coordinates[i][1] + t * (coordinates[i + 1][1] - coordinates[i][1]),
        metres: walked + t * Math.sqrt(length2),
      };
    }
    walked += Math.sqrt(length2);
  }
  return at;
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
