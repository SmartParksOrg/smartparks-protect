import { gpx, kml } from "@tmcw/togeojson";
import { unzipSync } from "fflate";
import shp from "shpjs";

/**
 * Shapes read from a file people already have (phase 33, decisions D268 and D269): a
 * shapefile as a zip, KML, KMZ, GPX or GeoJSON, parsed in the browser into the shapes the
 * Features page previews and saves as features. Nothing reaches the server but the features
 * a person keeps.
 */

export interface ImportedShape {
  id: string;
  /** From the file's `name` attribute when it has one, else numbered. */
  name: string;
  geometry: GeoJSON.Geometry;
  /** What the shape becomes unless the person says otherwise: a polygon a zone, a line a route,
   * a point a site. */
  featureType: "zone" | "route" | "site";
}

/** The most shapes one file may bring: a preview with more is no preview. */
export const MAX_SHAPES = 200;

export const ACCEPTED_EXTENSIONS = [
  ".zip",
  ".shp",
  ".kml",
  ".kmz",
  ".gpx",
  ".geojson",
  ".json",
];

const NAME_KEYS = ["name", "Name", "NAME", "title", "label", "id"];

function extensionOf(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot < 0 ? "" : fileName.slice(dot).toLowerCase();
}

/** Two dimensions only: KML and GPX carry an altitude the features API does not take. */
function flat(coordinates: unknown): unknown {
  if (!Array.isArray(coordinates)) return coordinates;
  if (coordinates.length > 0 && typeof coordinates[0] === "number")
    return coordinates.slice(0, 2);
  return coordinates.map(flat);
}

function flatGeometry(geometry: GeoJSON.Geometry): GeoJSON.Geometry[] {
  if (geometry.type === "GeometryCollection")
    return geometry.geometries.flatMap(flatGeometry);
  return [
    {
      type: geometry.type,
      coordinates: flat(geometry.coordinates),
    } as GeoJSON.Geometry,
  ];
}

function typeFor(geometry: GeoJSON.Geometry): ImportedShape["featureType"] {
  if (geometry.type === "Point" || geometry.type === "MultiPoint")
    return "site";
  if (geometry.type === "LineString" || geometry.type === "MultiLineString")
    return "route";
  return "zone";
}

function nameOf(properties: GeoJSON.GeoJsonProperties, index: number): string {
  for (const key of NAME_KEYS) {
    const value = properties?.[key];
    if (typeof value === "string" && value.trim())
      return value.trim().slice(0, 200);
    if (typeof value === "number") return String(value);
  }
  return `Shape ${index + 1}`;
}

/** The shapes of a GeoJSON document: a feature collection, one feature or a bare geometry;
 * a collection inside a geometry becomes one shape per part. */
export function shapesOfGeoJson(document: unknown): ImportedShape[] {
  const features: GeoJSON.Feature[] = [];
  const doc = document as { type?: string } | null;
  if (!doc || typeof doc !== "object" || !doc.type) return [];
  if (doc.type === "FeatureCollection")
    features.push(...((doc as GeoJSON.FeatureCollection).features ?? []));
  else if (doc.type === "Feature") features.push(doc as GeoJSON.Feature);
  else
    features.push({
      type: "Feature",
      geometry: doc as GeoJSON.Geometry,
      properties: {},
    });
  const out: ImportedShape[] = [];
  features.forEach((feature, index) => {
    if (!feature.geometry) return;
    const parts = flatGeometry(feature.geometry).filter(
      (g) =>
        "coordinates" in g &&
        Array.isArray(g.coordinates) &&
        g.coordinates.length > 0,
    );
    parts.forEach((geometry, part) => {
      const name = nameOf(feature.properties, index);
      out.push({
        id: `${index}-${part}`,
        name: parts.length > 1 ? `${name} (${part + 1})` : name,
        geometry,
        featureType: typeFor(geometry),
      });
    });
  });
  return out;
}

function parseXml(text: string): Document {
  const parsed = new DOMParser().parseFromString(text, "application/xml");
  if (parsed.getElementsByTagName("parsererror").length > 0)
    throw new Error("The file is not well-formed XML");
  return parsed;
}

function kmlOfKmz(bytes: Uint8Array): string {
  const entries = unzipSync(bytes);
  const name =
    Object.keys(entries).find((n) => n.toLowerCase() === "doc.kml") ??
    Object.keys(entries).find((n) => n.toLowerCase().endsWith(".kml"));
  if (!name) throw new Error("The KMZ holds no KML document");
  return new TextDecoder().decode(entries[name]);
}

/** Every shape of a file, by its extension. Throws with a plain reason when the file cannot
 * be read; a file with more than `MAX_SHAPES` shapes is refused rather than cut. */
export async function shapesOfFile(file: File): Promise<ImportedShape[]> {
  const extension = extensionOf(file.name);
  let shapes: ImportedShape[];
  if (extension === ".geojson" || extension === ".json")
    shapes = shapesOfGeoJson(JSON.parse(await file.text()));
  else if (extension === ".kml")
    shapes = shapesOfGeoJson(kml(parseXml(await file.text())));
  else if (extension === ".kmz")
    shapes = shapesOfGeoJson(
      kml(parseXml(kmlOfKmz(new Uint8Array(await file.arrayBuffer())))),
    );
  else if (extension === ".gpx")
    shapes = shapesOfGeoJson(gpx(parseXml(await file.text())));
  else if (extension === ".zip" || extension === ".shp") {
    const result = await shp(await file.arrayBuffer());
    const collections = Array.isArray(result) ? result : [result];
    shapes = collections.flatMap((collection, i) =>
      shapesOfGeoJson(collection).map((s) => ({ ...s, id: `${i}-${s.id}` })),
    );
  } else throw new Error(`Unknown file type ${extension || "(none)"}`);
  if (shapes.length > MAX_SHAPES)
    throw new Error(
      `The file holds ${shapes.length} shapes; at most ${MAX_SHAPES} are imported at once`,
    );
  return shapes;
}
