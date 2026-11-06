import type { CoverageResponse } from "@/api/types";

/**
 * Heard positions as toggles (decision D373, Tim, 2026-11-06: the same icon buttons as the
 * tracks and the heatmap, per entity, device and gateway, in the layers panel and on the
 * panels). The selection travels in the URL like the tracks (`heard`, `device_heard` and
 * `gateway_heard`, comma lists), and the map draws the union of what the selection asks for
 * and, when the Coverage tab's tick is on, everything heard in the view.
 */
export function listParam(params: URLSearchParams, key: string): string[] {
  return (params.get(key) ?? "").split(",").filter(Boolean);
}

export function toggleId(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export interface MergedCoverage {
  features: GeoJSON.Feature[];
  /** Distinct heard positions the two reads cover, the view's total plus what the selection
   * added beyond it. */
  total: number;
  /** The points drawn. */
  points: number;
}

/** The view's read and the selection's read as one layer: a position both answered is drawn
 * once (the point carries its id), the paths of both are kept. */
export function mergeCoverage(
  view: CoverageResponse | undefined,
  selected: CoverageResponse | undefined,
): MergedCoverage {
  const features: GeoJSON.Feature[] = [];
  const seen = new Set<number>();
  let points = 0;
  for (const response of [view, selected]) {
    if (!response) continue;
    for (const raw of response.features) {
      const feature = raw as unknown as GeoJSON.Feature;
      if (feature.geometry?.type === "Point") {
        const id = feature.properties?.id as number | undefined;
        if (id != null) {
          if (seen.has(id)) continue;
          seen.add(id);
        }
        points += 1;
      }
      features.push(feature);
    }
  }
  const viewTotal = view?.total ?? 0;
  const selectedTotal = selected?.total ?? 0;
  const viewPoints = view ? countPoints(view) : 0;
  const selectedPoints = selected ? countPoints(selected) : 0;
  // the overlap between the two reads is what the drawn points fell short of the sum by
  const overlap = viewPoints + selectedPoints - points;
  return { features, total: Math.max(0, viewTotal + selectedTotal - overlap), points };
}

function countPoints(response: CoverageResponse): number {
  return response.features.filter(
    (f) => (f as unknown as GeoJSON.Feature).geometry?.type === "Point",
  ).length;
}
