import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, RequestTransformFunction } from "maplibre-gl";
// MapLibre 6 runs in a module worker. Vite bundles it (with its shared chunk) when imported with
// `?worker&url`; without this the browser fetches a file that is not in the build.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { type RefObject, useEffect, useRef, useState } from "react";

import { BASEMAPS, type BasemapKey } from "@/components/map/basemap";
import { useAuthStore } from "@/stores/auth";

import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl(workerUrl);

/**
 * One MapLibre map bound to a container. Tile requests to our own API get the bearer token
 * through `transformRequest`; the base map needs nothing. The map is kept in a ref because it is
 * imperative; `ready` flips once the style has loaded so layers can be added.
 */
export function useMap(container: RefObject<HTMLDivElement | null>, basemap: BasemapKey, center: [number, number], zoom: number) {
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASEMAPS[basemap].style,
      center,
      zoom,
      attributionControl: { compact: true },
      transformRequest: ((url: string) => {
        if (url.startsWith(window.location.origin) || url.startsWith("/")) {
          const token = useAuthStore.getState().token;
          return { url, headers: token ? { Authorization: `Bearer ${token}` } : {} };
        }
        return { url };
      }) as RequestTransformFunction,
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.on("load", () => setReady(true));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // the map is created once; basemap changes go through setStyle below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setReady(false);
    map.setStyle(BASEMAPS[basemap].style);
    map.once("style.load", () => setReady(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap]);

  return { mapRef, ready };
}
