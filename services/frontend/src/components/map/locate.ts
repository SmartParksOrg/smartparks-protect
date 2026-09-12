import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

import { circleRing } from "@/lib/geodesy";

/**
 * The Locate toggle (decision D173): watch the browser's position, draw it as a dot with its
 * accuracy ring, and follow each fix with the map until the person pans, which keeps the dot
 * and stops the following; `stop` removes everything. Own code instead of MapLibre's
 * GeolocateControl so the button is one of the strip's and the states are ours.
 */
export type LocateStatus = "off" | "waiting" | "following" | "tracking" | "denied";

const SOURCE = "user-location";
const RING = "user-location-ring";
const DOT = "user-location-dot";
const DOT_OUTLINE = "user-location-dot-outline";

export interface LocateSession {
  stop(): void;
}

export function startLocate(
  map: MapLibreMap,
  onStatus: (status: LocateStatus) => void,
): LocateSession {
  if (!("geolocation" in navigator)) {
    onStatus("denied");
    return { stop() {} };
  }
  if (!map.getSource(SOURCE)) {
    map.addSource(SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: RING,
      type: "fill",
      source: SOURCE,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": "#52735E", "fill-opacity": 0.15 },
    });
    map.addLayer({
      id: DOT_OUTLINE,
      type: "circle",
      source: SOURCE,
      filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-radius": 9, "circle-color": "#ffffff" },
    });
    map.addLayer({
      id: DOT,
      type: "circle",
      source: SOURCE,
      filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-radius": 6, "circle-color": "#2F6FDB" },
    });
  }
  let following = true;
  const onDrag = () => {
    if (following) {
      following = false;
      onStatus("tracking");
    }
  };
  map.on("dragstart", onDrag);
  onStatus("waiting");
  const watch = navigator.geolocation.watchPosition(
    (position) => {
      const centre: [number, number] = [position.coords.longitude, position.coords.latitude];
      const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
      source?.setData({
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [circleRing(centre, Math.max(position.coords.accuracy, 1))] } },
          { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: centre } },
        ],
      });
      if (following) {
        map.easeTo({ center: centre, zoom: Math.max(map.getZoom(), 14), duration: 600 });
        onStatus("following");
      }
    },
    () => onStatus("denied"),
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
  );
  return {
    stop() {
      navigator.geolocation.clearWatch(watch);
      map.off("dragstart", onDrag);
      for (const id of [DOT, DOT_OUTLINE, RING]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
      onStatus("off");
    },
  };
}
