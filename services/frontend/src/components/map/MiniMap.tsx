import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { useTranslation } from "react-i18next";
import { useEffect, useRef } from "react";
import { Link } from "react-router";

import type { Position } from "@/api/types";
import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import { maplibregl } from "@/components/map/maplibre";
import { miniMapGeometry } from "@/components/map/miniMap";
import { useTheme } from "@/hooks/useTheme";

const TRAIL = "mini-trail";
const LATEST = "mini-latest";

/** A still map of where something is (decision D124): the newest position with a short trail,
 * fitted to the trail; no gestures, so the page scrolls as usual, and the whole map is a link to
 * the live map on the object.
 *
 * The map fills its container and never shrinks below `min-h-56`, so a caller that sets a height
 * gives it `h-56` or more; a shorter box lets the map spill over what follows it (Tim,
 * 2026-09-18: the gateway dialog's "Open in ..." button sat under the map). */
export function MiniMap({
  positions = [],
  point,
  to,
  label,
  onPick,
  fallback,
}: {
  /** Positions newest first: the newest is marked, the rest is the trail. */
  positions?: Position[];
  /** One fixed place instead, [lon, lat]: a gateway. */
  point?: [number, number];
  to: string;
  label?: string;
  /** With it the map takes gestures and a click places the point (decision D239: a gateway
   * without a location is put on the map by hand); the map is no link then. */
  onPick?: (lonLat: [number, number]) => void;
  /** Where to look when there is no point yet and the map is for picking, [lon, lat]. */
  fallback?: [number, number];
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const pendingRef = useRef<(() => void) | null>(null);
  const pickRef = useRef(onPick);
  useEffect(() => {
    pickRef.current = onPick;
  }, [onPick]);
  const picking = onPick !== undefined;
  const geometry = point
    ? {
        line: [],
        latest: point,
        bounds: [point[0], point[1], point[0], point[1]] as [
          number,
          number,
          number,
          number,
        ],
      }
    : miniMapGeometry(positions);
  const hasGeometry = geometry !== null || picking;

  const { resolved } = useTheme();
  const dark = resolved === "dark";
  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: basemapStyle(loadBasemap(), basemapsFor(null), dark),
      center: fallback ?? [0, 0],
      zoom: fallback ? 12 : 1,
      interactive: picking,
      attributionControl: false,
    });
    if (picking) {
      map.getCanvas().style.cursor = "crosshair";
      map.on("click", (e) =>
        pickRef.current?.([
          Number(e.lngLat.lng.toFixed(6)),
          Number(e.lngLat.lat.toFixed(6)),
        ]),
      );
    }
    map.on("load", () => {
      map.addSource(TRAIL, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addSource(LATEST, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: TRAIL,
        type: "line",
        source: TRAIL,
        paint: {
          "line-color": "#2f5d50",
          "line-width": 2,
          "line-opacity": 0.7,
        },
      });
      map.addLayer({
        id: `${LATEST}-ring`,
        type: "circle",
        source: LATEST,
        paint: {
          "circle-radius": 9,
          "circle-color": "#ffffff",
          "circle-opacity": 0.95,
        },
      });
      map.addLayer({
        id: LATEST,
        type: "circle",
        source: LATEST,
        paint: { "circle-radius": 6, "circle-color": "#2f5d50" },
      });
      readyRef.current = true;
      pendingRef.current?.();
      pendingRef.current = null;
    });
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container.current);
    mapRef.current = map;
    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
  }, [hasGeometry, dark, picking]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !geometry) return;
    const draw = () => {
      (map.getSource(TRAIL) as GeoJSONSource | undefined)?.setData({
        type: "FeatureCollection",
        features:
          geometry.line.length > 1
            ? [
                {
                  type: "Feature",
                  properties: {},
                  geometry: { type: "LineString", coordinates: geometry.line },
                },
              ]
            : [],
      });
      (map.getSource(LATEST) as GeoJSONSource | undefined)?.setData({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {},
            geometry: { type: "Point", coordinates: geometry.latest },
          },
        ],
      });
      const [west, south, east, north] = geometry.bounds;
      if (picking) {
        // the person is placing the point: keep their view, unless it is still the world
        if (map.getZoom() < 3)
          map.jumpTo({ center: geometry.latest, zoom: 13 });
      } else if (west === east && south === north)
        map.jumpTo({ center: geometry.latest, zoom: 13 });
      else
        map.fitBounds([west, south, east, north], {
          padding: 36,
          maxZoom: 15,
          duration: 0,
        });
    };
    if (readyRef.current) draw();
    else pendingRef.current = draw;
    return () => {
      if (pendingRef.current === draw) pendingRef.current = null;
    };
  }, [geometry?.latest[0], geometry?.latest[1], geometry?.line.length]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!geometry && !picking) {
    return (
      <div className="flex h-full min-h-56 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
        {t("No position yet.")}
      </div>
    );
  }
  if (picking) {
    return (
      <div className="relative block h-full min-h-56 overflow-hidden rounded-xl border shadow-sm">
        <div ref={container} className="h-full w-full" />
        <span className="pointer-events-none absolute right-2 top-2 rounded bg-card/90 px-2 py-0.5 text-xs shadow-sm">
          {label ?? t("Click to place")}
        </span>
      </div>
    );
  }
  return (
    <Link
      to={to}
      aria-label={label ?? t("Open in live map")}
      className="relative block h-full min-h-56 overflow-hidden rounded-xl border shadow-sm"
    >
      <div ref={container} className="h-full w-full" />
      <span className="pointer-events-none absolute right-2 top-2 rounded bg-card/90 px-2 py-0.5 text-xs shadow-sm">
        {label ?? t("Open in live map")}
      </span>
      <span className="pointer-events-none absolute bottom-0 right-0 bg-card/80 px-1 text-[10px] text-muted-foreground">
        {t("© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors")}
      </span>
    </Link>
  );
}
