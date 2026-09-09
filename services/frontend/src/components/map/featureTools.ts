/** What a drawn geometry can become and which rule a feature starts (decisions D139, D140). */

export type FeatureType = "site" | "zone" | "geofence" | "route";

/** The types a drawn geometry can become: a point a site, a line a route, a polygon a
 * geofence or a zone. */
export function featureTypesFor(
  geometry: GeoJSON.Geometry | null,
): FeatureType[] {
  if (geometry?.type === "Point") return ["site"];
  if (geometry?.type === "LineString") return ["route"];
  return ["geofence", "zone"];
}

/** The rule template a feature type starts from: a geofence the exit rule, a site or zone the
 * proximity rule, a route nothing. */
export function ruleTemplateFor(featureType: string): string | null {
  if (featureType === "geofence") return "geofence_exit";
  if (featureType === "site" || featureType === "zone") return "near_site";
  return null;
}
