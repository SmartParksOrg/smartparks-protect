import type {
  IControl,
  Map as MapLibreMap,
  RequestTransformFunction,
} from "maplibre-gl";
import { type RefObject, useEffect, useRef, useState } from "react";

import { maplibregl } from "@/components/map/maplibre";
import { useAuthStore } from "@/stores/auth";

/** An empty MapLibre control the page renders the control strip into (decision D137), so the
 * strip stacks under the map's own buttons whatever their height. */
class StripHost implements IControl {
  readonly element = document.createElement("div");

  onAdd(): HTMLElement {
    this.element.className = "maplibregl-ctrl protect-strip";
    return this.element;
  }

  onRemove(): void {
    this.element.remove();
  }
}

/**
 * One MapLibre map bound to a container. Tile requests to our own API get the bearer token
 * through `transformRequest`; the base map needs nothing. The map is kept in a ref because it is
 * imperative; `ready` flips once the style has loaded so layers can be added.
 */
export function useMap(
  container: RefObject<HTMLDivElement | null>,
  style: string,
  center: [number, number],
  zoom: number,
) {
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [stripHost, setStripHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style,
      center,
      zoom,
      attributionControl: { compact: true },
      transformRequest: ((url: string) => {
        if (url.startsWith(window.location.origin) || url.startsWith("/")) {
          const token = useAuthStore.getState().token;
          return {
            url,
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          };
        }
        return { url };
      }) as RequestTransformFunction,
    });
    map.addControl(
      new maplibregl.NavigationControl({ visualizePitch: true }),
      "top-right",
    );
    // "My location": the browser's geolocation, centred once with a marker; the control
    // explains a refused permission itself (phase 15).
    map.addControl(
      new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: false,
        showUserLocation: true,
      }),
      "top-right",
    );
    const strip = new StripHost();
    map.addControl(strip, "top-right");
    setStripHost(strip.element);
    map.addControl(
      new maplibregl.ScaleControl({ unit: "metric" }),
      "bottom-left",
    );
    map.on("load", () => {
      // MapLibre opens the compact attribution on load; on a phone it then covers the bottom
      // of the map until tapped, so start it folded to the button
      map
        .getContainer()
        .querySelector(".maplibregl-ctrl-attrib")
        ?.classList.remove("maplibregl-compact-show");
      setReady(true);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
      setStripHost(null);
    };
    // the map is created once; basemap changes go through setStyle below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setReady(false);
    map.setStyle(style);
    map.once("style.load", () => setReady(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [style]);

  return { mapRef, ready, stripHost };
}
