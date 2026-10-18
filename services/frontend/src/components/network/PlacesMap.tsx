import type { Map as MapLibreMap, Marker } from "maplibre-gl";
import { List, Map as MapIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router";

import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import { maplibregl } from "@/components/map/maplibre";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";

/** One thing on the map: where it is, what it is called, its icon as SVG markup, where a
 * press takes the person. */
export interface Place {
  id: string;
  name: string;
  lonLat: [number, number];
  /** Raw SVG markup from the icon registry; drawn in the marker's own colour. */
  icon: string;
  to: string;
  /** The tooltip; the name when absent. */
  title?: string;
}

export type ListOrMap = "list" | "map";

/** The two buttons, list or map, for the heading of a section that offers both. */
export function ListMapSwitch({
  view,
  onView,
}: {
  view: ListOrMap;
  onView: (view: ListOrMap) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex rounded-md border p-0.5"
      role="group"
      aria-label={t("View")}
    >
      <Button
        type="button"
        variant={view === "list" ? "secondary" : "ghost"}
        size="icon"
        className="size-7"
        aria-pressed={view === "list"}
        aria-label={t("List")}
        onClick={() => onView("list")}
      >
        <List className="size-4" />
      </Button>
      <Button
        type="button"
        variant={view === "map" ? "secondary" : "ghost"}
        size="icon"
        className="size-7"
        aria-pressed={view === "map"}
        aria-label={t("Map")}
        onClick={() => onView("map")}
      >
        <MapIcon className="size-4" />
      </Button>
    </div>
  );
}

/** A place's marker: its icon in a white disc, its name under it; a press opens its page.
 * Built from DOM nodes, so a name is text, never markup. The icon takes the disc's own colour,
 * not the page's text colour, which is white in dark mode and vanished on the white disc
 * (Tim, 2026-10-18). */
function markerElement(place: Place, onOpen: () => void): HTMLElement {
  const el = document.createElement("button");
  el.type = "button";
  el.className = "flex cursor-pointer flex-col items-center";
  el.title = place.title ?? place.name;
  const disc = document.createElement("span");
  disc.className =
    "flex size-8 items-center justify-center rounded-full border-2 border-[#2f5d50] bg-white text-[#2f5d50] shadow [&>svg]:size-5";
  disc.innerHTML = place.icon;
  const label = document.createElement("span");
  label.className =
    "mt-0.5 rounded bg-card/90 px-1 text-[11px] font-medium shadow-sm";
  label.textContent = place.name;
  el.append(disc, label);
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    onOpen();
  });
  return el;
}

/**
 * A small map of places on the Offload page (Tim, 2026-10-18: the stations, then the trackers'
 * last known positions, each section a list or a map): every place as a named marker, fitted
 * to all of them; a press on a marker opens the place's page, the corner link opens the live
 * map. The map pans and zooms by drag and buttons, not by the wheel, so the page keeps
 * scrolling over it. What has no place yet is counted under the map.
 */
export function PlacesMap({
  places,
  unplaced,
  unplacedNote,
  emptyMessage,
  liveMapTo,
}: {
  places: Place[];
  /** How many of the section's rows have no place and so are not on the map. */
  unplaced: number;
  /** The line under the map that counts them; it takes `count`. */
  unplacedNote: string;
  /** What the map says when nothing has a place. */
  emptyMessage: string;
  liveMapTo: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const readyRef = useRef(false);
  const pendingRef = useRef<(() => void) | null>(null);
  const { resolved } = useTheme();
  const dark = resolved === "dark";

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: basemapStyle(loadBasemap(), basemapsFor(null), dark),
      center: [0, 0],
      zoom: 1,
      attributionControl: false,
    });
    map.scrollZoom.disable();
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-left",
    );
    map.on("load", () => {
      readyRef.current = true;
      pendingRef.current?.();
      pendingRef.current = null;
    });
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container.current);
    mapRef.current = map;
    return () => {
      observer.disconnect();
      for (const m of markersRef.current) m.remove();
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
  }, [dark]);

  const key = places
    .map((p) => `${p.id}:${p.lonLat.join(",")}:${p.name}:${p.to}`)
    .join("|");
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const draw = () => {
      for (const m of markersRef.current) m.remove();
      markersRef.current = places.map((p) =>
        new maplibregl.Marker({
          element: markerElement(p, () => navigate(p.to)),
          anchor: "top",
        })
          .setLngLat(p.lonLat)
          .addTo(map),
      );
      if (places.length === 0) return;
      if (places.length === 1) {
        map.jumpTo({ center: places[0].lonLat, zoom: 13 });
        return;
      }
      const lons = places.map((p) => p.lonLat[0]);
      const lats = places.map((p) => p.lonLat[1]);
      map.fitBounds(
        [
          Math.min(...lons),
          Math.min(...lats),
          Math.max(...lons),
          Math.max(...lats),
        ],
        {
          padding: { top: 48, bottom: 48, left: 64, right: 64 },
          maxZoom: 14,
          duration: 0,
        },
      );
    };
    if (readyRef.current) draw();
    else pendingRef.current = draw;
    return () => {
      if (pendingRef.current === draw) pendingRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, dark]);

  if (places.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-xl border border-dashed p-4 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <div className="relative h-72 overflow-hidden rounded-xl border shadow-sm md:h-96">
        <div ref={container} className="h-full w-full" />
        <Link
          to={liveMapTo}
          className="absolute right-2 top-2 rounded bg-card/90 px-2 py-0.5 text-xs shadow-sm hover:underline"
        >
          {t("Open in live map")}
        </Link>
        <span className="pointer-events-none absolute bottom-0 right-0 bg-card/80 px-1 text-[10px] text-muted-foreground">
          {t("© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors")}
        </span>
      </div>
      {unplaced > 0 && (
        <p className="text-xs text-muted-foreground">{unplacedNote}</p>
      )}
    </div>
  );
}
