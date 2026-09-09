import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * 3D terrain (decision D141): a raster DEM source with a hillshade layer under the data, and
 * MapLibre's terrain on top of any base map. The tiles come from MapTiler with the server's
 * key; a style change drops sources and layers, so the map page applies this again when the
 * style has loaded.
 */
export const TERRAIN_SOURCE = "terrain-dem";
const HILLSHADE_LAYER = "terrain-hillshade";
export const TERRAIN_EXAGGERATION = 1.3;
export const TERRAIN_PITCH = 55;

/** MapTiler's terrain RGB tiles as a TileJSON source. */
export function terrainTileJson(maptilerKey: string): string {
  return `https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key=${encodeURIComponent(maptilerKey)}`;
}

/** The layer the hillshade goes under: the first of our data layers present, else the top. */
function firstDataLayer(map: MapLibreMap): string | undefined {
  for (const id of [
    "heat",
    "coverage-hex",
    "coverage-points",
    "features-fill",
    "gateway-markers",
    "entity-clusters",
  ])
    if (map.getLayer(id)) return id;
  return undefined;
}

export function setTerrain(map: MapLibreMap, tileJsonUrl: string | null): void {
  if (!tileJsonUrl) {
    if (map.getTerrain()) map.setTerrain(null);
    if (map.getLayer(HILLSHADE_LAYER)) map.removeLayer(HILLSHADE_LAYER);
    if (map.getSource(TERRAIN_SOURCE)) map.removeSource(TERRAIN_SOURCE);
    return;
  }
  if (!map.getSource(TERRAIN_SOURCE))
    map.addSource(TERRAIN_SOURCE, {
      type: "raster-dem",
      url: tileJsonUrl,
      tileSize: 256,
    });
  if (!map.getLayer(HILLSHADE_LAYER))
    map.addLayer(
      {
        id: HILLSHADE_LAYER,
        type: "hillshade",
        source: TERRAIN_SOURCE,
        paint: {
          "hillshade-shadow-color": "#473B24",
          "hillshade-exaggeration": 0.4,
        },
      },
      firstDataLayer(map),
    );
  if (!map.getTerrain())
    map.setTerrain({
      source: TERRAIN_SOURCE,
      exaggeration: TERRAIN_EXAGGERATION,
    });
}
