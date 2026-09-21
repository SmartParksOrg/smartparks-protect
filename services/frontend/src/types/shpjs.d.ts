/** shpjs ships no declarations: the one call we make, a zip or a .shp buffer to GeoJSON. */
declare module "shpjs" {
  type Collection = GeoJSON.FeatureCollection & { fileName?: string };
  function shp(input: ArrayBuffer | string): Promise<Collection | Collection[]>;
  export default shp;
}
