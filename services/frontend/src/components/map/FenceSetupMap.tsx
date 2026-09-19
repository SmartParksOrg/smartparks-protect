import { useTranslation } from "react-i18next";
import type { GeoJSONSource } from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { FenceMonitorItem } from "@/api/types";
import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import { geometryBounds } from "@/components/map/fit";
import { maplibregl } from "@/components/map/maplibre";
import { useMap } from "@/components/map/useMap";
import { useTheme } from "@/hooks/useTheme";
import { type FenceSection, fenceColor, nearestOnLine } from "@/lib/fence";

const LINE = "fence-setup-line";
const SNAP = "fence-setup-snap";
export const DRAG_TYPE = "application/x-protect-fence-monitor";

/** A monitor on the map: a point on the line in its level's colour, never a label (Tim,
 * 2026-09-19). The name is the tooltip and the list beside the map. */
function dot(color: string): HTMLDivElement {
  const element = document.createElement("div");
  element.style.width = "18px";
  element.style.height = "18px";
  element.style.borderRadius = "9999px";
  element.style.border = "3px solid #ffffff";
  element.style.boxShadow =
    "0 0 0 1px rgba(0,0,0,0.25), 0 1px 3px rgba(0,0,0,0.3)";
  element.style.background = color;
  element.style.cursor = "grab";
  return element;
}

/**
 * The map a fence line is set up on (Tim, 2026-09-19): the line in its sections' colours and
 * the monitors on it as markers that drag along it; a monitor from the list beside the map is
 * dropped anywhere on the line. Where the pointer lets go is moved onto the line at once, and
 * the server does the same and makes it the device's fixed place.
 */
export function FenceSetupMap({
  line,
  sections,
  monitors,
  levels,
  onPlace,
}: {
  line: GeoJSON.LineString;
  sections: FenceSection[];
  /** The monitors on this line, with where they stand. */
  monitors: FenceMonitorItem[];
  /** Each monitor's level, for the colour of its point. */
  levels: Record<string, string>;
  onPlace: (entityId: string, lon: number, lat: number) => void;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const { resolved: resolvedTheme } = useTheme();
  const { mapRef, ready } = useMap(
    container,
    basemapStyle(loadBasemap(), basemapsFor(null), resolvedTheme === "dark"),
    [line.coordinates[0][0], line.coordinates[0][1]],
    13,
  );
  const markers = useRef<Map<string, maplibregl.Marker>>(new Map());
  const placeRef = useRef(onPlace);
  useEffect(() => {
    placeRef.current = onPlace;
  }, [onPlace]);
  const coordinates = line.coordinates as number[][];

  // the line, once, and the view fitted to it
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!map.getSource(LINE)) {
      map.addSource(LINE, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: `${LINE}-casing`,
        type: "line",
        source: LINE,
        paint: {
          "line-color": "#ffffff",
          "line-width": 8,
          "line-opacity": 0.8,
        },
      });
      map.addLayer({
        id: LINE,
        type: "line",
        source: LINE,
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#8A9590"],
          "line-width": 5,
        },
      });
      // where a dragged monitor will land: a ring on the line that follows the pointer
      map.addSource(SNAP, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: SNAP,
        type: "circle",
        source: SNAP,
        paint: {
          "circle-radius": 11,
          "circle-color": "#ffffff",
          "circle-opacity": 0.6,
          "circle-stroke-color": "#2F4A3A",
          "circle-stroke-width": 2,
        },
      });
      const bounds = geometryBounds([{ geometry: line }]);
      if (bounds)
        map.fitBounds(bounds, { padding: 60, duration: 0, maxZoom: 15 });
    }
  }, [mapRef, ready, line]);
  const showSnap = (lon: number, lat: number) => {
    (mapRef.current?.getSource(SNAP) as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: { type: "Point", coordinates: [lon, lat] },
        },
      ],
    });
  };
  const hideSnap = () => {
    (mapRef.current?.getSource(SNAP) as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: [],
    });
  };

  // the sections in their colours (one piece per section, like the live map)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource(LINE) as GeoJSONSource | undefined;
    if (!source) return;
    const pieces: GeoJSON.Feature[] =
      sections.length > 0
        ? sections.map((s) => ({
            type: "Feature",
            properties: { color: fenceColor(s.level) },
            geometry: {
              type: "LineString",
              coordinates: sliceByMetres(coordinates, s.from_m, s.to_m),
            },
          }))
        : [{ type: "Feature", properties: {}, geometry: line }];
    source.setData({ type: "FeatureCollection", features: pieces });
  }, [mapRef, ready, sections, line, coordinates]);

  // a marker per monitor on the line, draggable along it
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const seen = new Set<string>();
    for (const m of monitors) {
      if (m.longitude == null || m.latitude == null) continue;
      seen.add(m.entity_id);
      let marker = markers.current.get(m.entity_id);
      const color = fenceColor(levels[m.entity_id]);
      if (!marker) {
        const element = dot(color);
        element.title = `${m.name} · ${t("Drag along the line to move it")}`;
        marker = new maplibregl.Marker({
          element,
          draggable: true,
          anchor: "center",
        })
          .setLngLat([m.longitude, m.latitude])
          .addTo(map);
        const id = m.entity_id;
        // while it is dragged, the ring shows where on the line it will land; when it is
        // let go it goes there, so a point never sits beside the line
        marker.on("drag", () => {
          const { lng, lat } = marker!.getLngLat();
          const at = nearestOnLine(coordinates, lng, lat);
          showSnap(at.lon, at.lat);
        });
        marker.on("dragend", () => {
          const { lng, lat } = marker!.getLngLat();
          const at = nearestOnLine(coordinates, lng, lat);
          marker!.setLngLat([at.lon, at.lat]);
          hideSnap();
          placeRef.current(id, at.lon, at.lat);
        });
        markers.current.set(m.entity_id, marker);
      } else {
        marker.setLngLat([m.longitude, m.latitude]);
        marker.getElement().style.background = color;
        marker.getElement().title = `${m.name} · ${t("Drag along the line to move it")}`;
      }
    }
    for (const [id, marker] of markers.current) {
      if (!seen.has(id)) {
        marker.remove();
        markers.current.delete(id);
      }
    }
  }, [mapRef, ready, monitors, levels, coordinates, t]);
  useEffect(() => {
    const held = markers.current;
    return () => {
      for (const marker of held.values()) marker.remove();
      held.clear();
    };
  }, []);

  // a monitor from the list, dragged over the map and dropped: the ring shows where on the
  // line it will land, and it lands there
  const under = (event: React.DragEvent<HTMLDivElement>) => {
    const map = mapRef.current;
    if (!map || !container.current) return null;
    const rect = container.current.getBoundingClientRect();
    const { lng, lat } = map.unproject([
      event.clientX - rect.left,
      event.clientY - rect.top,
    ]);
    return nearestOnLine(coordinates, lng, lat);
  };
  const drop = (event: React.DragEvent<HTMLDivElement>) => {
    const id = event.dataTransfer.getData(DRAG_TYPE);
    const at = under(event);
    hideSnap();
    if (!id || !at) return;
    event.preventDefault();
    placeRef.current(id, at.lon, at.lat);
  };
  return (
    <div
      ref={container}
      className="h-80 w-full rounded-md border"
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
        e.preventDefault();
        const at = under(e);
        if (at) showSnap(at.lon, at.lat);
      }}
      onDragLeave={hideSnap}
      onDrop={drop}
      role="application"
      aria-label={t(
        "The fence line and its monitors; drop a monitor on the line to place it",
      )}
    />
  );
}

/** The part of the line between two distances along it, by the same flat frame the fence
 * helpers use; the live map does the same for its sections. */
function sliceByMetres(
  coordinates: number[][],
  fromM: number,
  toM: number,
): number[][] {
  const start = nearestOnLine(coordinates, ...pointAt(coordinates, fromM));
  const end = nearestOnLine(coordinates, ...pointAt(coordinates, toM));
  const out: number[][] = [[start.lon, start.lat]];
  let walked = 0;
  for (let i = 0; i < coordinates.length - 1; i += 1) {
    const step = nearestOnLine(
      [coordinates[i], coordinates[i + 1]],
      coordinates[i + 1][0],
      coordinates[i + 1][1],
    ).metres;
    const vertexAt = walked + step;
    if (vertexAt > fromM && vertexAt < toM) out.push(coordinates[i + 1]);
    walked = vertexAt;
  }
  out.push([end.lon, end.lat]);
  return out;
}

function pointAt(coordinates: number[][], metres: number): [number, number] {
  // walk the line to the point `metres` along it
  let walked = 0;
  for (let i = 0; i < coordinates.length - 1; i += 1) {
    const step = nearestOnLine(
      [coordinates[i], coordinates[i + 1]],
      coordinates[i + 1][0],
      coordinates[i + 1][1],
    ).metres;
    if (step > 0 && walked + step >= metres) {
      const t = (metres - walked) / step;
      return [
        coordinates[i][0] + t * (coordinates[i + 1][0] - coordinates[i][0]),
        coordinates[i][1] + t * (coordinates[i + 1][1] - coordinates[i][1]),
      ];
    }
    walked += step;
  }
  const last = coordinates[coordinates.length - 1];
  return [last[0], last[1]];
}
