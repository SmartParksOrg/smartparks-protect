import type { Map as MapLibreMap, Marker } from "maplibre-gl";
import { useTranslation } from "react-i18next";
import { useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router";

import type { OffloadOverviewStation } from "@/api/types";
import { resolveIcon } from "@/components/icons/registry";
import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import { maplibregl } from "@/components/map/maplibre";
import { useTheme } from "@/hooks/useTheme";

type Placed = OffloadOverviewStation & { lonLat: [number, number] };

function placed(stations: OffloadOverviewStation[]): Placed[] {
  const out: Placed[] = [];
  for (const s of stations) {
    const c = (s.location as { coordinates?: number[] } | null)?.coordinates;
    if (c && c.length >= 2) out.push({ ...s, lonLat: [c[0], c[1]] });
  }
  return out;
}

/** A station's marker: Protect's station icon in a white disc, the device's name under it; a
 * press opens the device's page. Built from DOM nodes, so a name is text, never markup. */
function markerElement(
  station: Placed,
  icon: string,
  onOpen: () => void,
): HTMLElement {
  const el = document.createElement("button");
  el.type = "button";
  el.className = "flex cursor-pointer flex-col items-center";
  el.title = station.station_eui
    ? `${station.device_name} · ${station.station_eui}`
    : station.device_name;
  const disc = document.createElement("span");
  disc.className =
    "flex size-8 items-center justify-center rounded-full border-2 border-[#2f5d50] bg-white shadow [&>svg]:size-5";
  disc.innerHTML = icon;
  const label = document.createElement("span");
  label.className =
    "mt-0.5 rounded bg-card/90 px-1 text-[11px] font-medium shadow-sm";
  label.textContent = station.device_name;
  el.append(disc, label);
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    onOpen();
  });
  return el;
}

/**
 * The project's offload stations on a small map (Tim, 2026-10-18: a map view of the Stations
 * section, toggled with the list): every station with a place as Protect's station marker,
 * named, fitted to all of them; a press on a marker opens the station's device page, the
 * corner link opens the live map. The map pans and zooms by drag and buttons, not by the
 * wheel, so the page keeps scrolling over it. Stations without a place are counted under it.
 */
export function StationsMap({
  stations,
  projectId,
}: {
  stations: OffloadOverviewStation[];
  projectId: string;
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
  const shown = placed(stations);
  const unplaced = stations.length - shown.length;
  const icon = resolveIcon("device.lora_gateway").svg;

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

  const key = shown
    .map((s) => `${s.device_id}:${s.lonLat.join(",")}:${s.device_name}`)
    .join("|");
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const draw = () => {
      for (const m of markersRef.current) m.remove();
      markersRef.current = shown.map((s) =>
        new maplibregl.Marker({
          element: markerElement(s, icon, () =>
            navigate(`/projects/${projectId}/devices/${s.device_id}`),
          ),
          anchor: "top",
        })
          .setLngLat(s.lonLat)
          .addTo(map),
      );
      if (shown.length === 0) return;
      if (shown.length === 1) {
        map.jumpTo({ center: shown[0].lonLat, zoom: 13 });
        return;
      }
      const lons = shown.map((s) => s.lonLat[0]);
      const lats = shown.map((s) => s.lonLat[1]);
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
  }, [key, icon, projectId, dark]);

  if (shown.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-xl border border-dashed p-4 text-center text-sm text-muted-foreground">
        {stations.length === 0
          ? t("No offload station yet.")
          : t(
              "None of the stations has a place yet. Set it on the station's device page, under Place, or in the station dialog.",
            )}
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <div className="relative h-72 overflow-hidden rounded-xl border shadow-sm md:h-96">
        <div ref={container} className="h-full w-full" />
        <Link
          to={`/projects/${projectId}/map`}
          className="absolute right-2 top-2 rounded bg-card/90 px-2 py-0.5 text-xs shadow-sm hover:underline"
        >
          {t("Open in live map")}
        </Link>
        <span className="pointer-events-none absolute bottom-0 right-0 bg-card/80 px-1 text-[10px] text-muted-foreground">
          {t("© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors")}
        </span>
      </div>
      {unplaced > 0 && (
        <p className="text-xs text-muted-foreground">
          {t(
            "{{count}} stations without a place are not on the map; the list names them.",
            {
              count: unplaced,
            },
          )}
        </p>
      )}
    </div>
  );
}
