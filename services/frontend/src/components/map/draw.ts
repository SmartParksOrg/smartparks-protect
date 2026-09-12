import type { Map as MapLibreMap } from "maplibre-gl";
import {
  TerraDraw,
  TerraDrawCircleMode,
  TerraDrawLineStringMode,
  TerraDrawPointMode,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";

import { polygonCentre } from "@/lib/geodesy";

/**
 * Drawing on a MapLibre map with terra-draw (decisions D139, D171, D172): one instance per map
 * with a point, a line, a polygon and a circle mode plus a select mode, in the brand colours.
 * Every vertex carries a marker from the first tap, the shape in progress is reported on every
 * change so the bar measures it live, and a closed shape stays editable (vertices dragged,
 * added on a midpoint or deleted) until it is kept. Escape cancels, Enter finishes (the
 * library's key events). The live map and the Features page share it.
 */
export type DrawKind = "point" | "line" | "polygon" | "circle";

const MODE_OF: Record<DrawKind, string> = {
  point: "point",
  line: "linestring",
  polygon: "polygon",
  circle: "circle",
};

/** What the session holds: the shape still being drawn or the finished one, and for a circle
 * its centre and radius (terra-draw keeps the radius on the feature). */
export interface DrawState {
  /** The finished shape, null while nothing is finished. */
  geometry: GeoJSON.Geometry | null;
  /** The shape in progress, or the finished one; what the bar measures. */
  live: GeoJSON.Geometry | null;
  /** Set for a circle: its centre and radius in metres. */
  circle: { centre: [number, number]; radius_m: number } | null;
}

export const EMPTY_DRAW: DrawState = { geometry: null, live: null, circle: null };

export interface DrawSession {
  /** Start drawing a kind of geometry; a finished feature stays editable. */
  begin(kind: DrawKind): void;
  /** The current state. */
  state(): DrawState;
  /** Remove everything drawn. */
  clear(): void;
  /** Stop drawing and remove the layers. */
  destroy(): void;
}

type Hex = `#${string}`;
const GREEN: Hex = "#52735E";
const LIGHT: Hex = "#90AE9B";
const SAND: Hex = "#C6B187";
const WHITE: Hex = "#ffffff";

const VERTEX = {
  coordinatePointColor: GREEN,
  coordinatePointOutlineColor: WHITE,
  coordinatePointOutlineWidth: 2,
  coordinatePointWidth: 6,
  closingPointColor: SAND,
  closingPointOutlineColor: WHITE,
  closingPointOutlineWidth: 2,
  closingPointWidth: 7,
};

export function createDrawSession(
  map: MapLibreMap,
  onChange: (state: DrawState) => void,
): DrawSession {
  const draw = new TerraDraw({
    adapter: new TerraDrawMapLibreGLAdapter({ map, coordinatePrecision: 6 }),
    modes: [
      new TerraDrawPointMode({
        editable: true,
        styles: {
          pointColor: GREEN,
          pointOutlineColor: WHITE,
          pointOutlineWidth: 2,
          pointWidth: 7,
        },
      }),
      new TerraDrawLineStringMode({
        editable: true,
        showCoordinatePoints: true,
        keyEvents: { cancel: "Escape", finish: "Enter" },
        styles: { lineStringColor: GREEN, lineStringWidth: 3, ...VERTEX },
      }),
      new TerraDrawPolygonMode({
        editable: true,
        showCoordinatePoints: true,
        keyEvents: { cancel: "Escape", finish: "Enter" },
        styles: {
          fillColor: LIGHT,
          fillOpacity: 0.3,
          outlineColor: GREEN,
          outlineWidth: 2,
          ...VERTEX,
        },
      }),
      new TerraDrawCircleMode({
        segments: 64,
        keyEvents: { cancel: "Escape", finish: "Enter" },
        styles: {
          fillColor: LIGHT,
          fillOpacity: 0.3,
          outlineColor: GREEN,
          outlineWidth: 2,
        },
      }),
      new TerraDrawSelectMode({
        flags: {
          point: { feature: { draggable: true } },
          linestring: {
            feature: {
              draggable: true,
              coordinates: { midpoints: true, draggable: true, deletable: true },
            },
          },
          polygon: {
            feature: {
              draggable: true,
              coordinates: { midpoints: true, draggable: true, deletable: true },
            },
          },
          circle: { feature: { draggable: true } },
        },
        styles: {
          selectedPolygonColor: LIGHT,
          selectedPolygonFillOpacity: 0.3,
          selectedPolygonOutlineColor: GREEN,
          selectedLineStringColor: GREEN,
          selectedPointColor: GREEN,
          selectionPointColor: WHITE,
          selectionPointOutlineColor: GREEN,
          midPointColor: SAND,
          midPointOutlineColor: WHITE,
        },
      }),
    ],
  });
  draw.start();

  const shapes = () =>
    draw.getSnapshot().filter(
      (f) =>
        !f.properties.midPoint &&
        !f.properties.selectionPoint &&
        !f.properties.coordinatePoint &&
        !f.properties.closingPoint &&
        !f.properties.snappingPoint,
    );
  const current = (): DrawState => {
    const all = shapes();
    const done = all.filter((f) => !f.properties.currentlyDrawing);
    const finished = done.length > 0 ? done[done.length - 1] : null;
    const live = all.length > 0 ? all[all.length - 1] : null;
    const shape = finished ?? live;
    const radiusKm = shape?.properties.radiusKilometers;
    // the radius is on the feature from the first tap, at nothing until the pointer moves
    const circle =
      shape &&
      shape.geometry.type === "Polygon" &&
      typeof radiusKm === "number" &&
      radiusKm * 1000 >= 1
        ? {
            centre: polygonCentre(
              shape.geometry.coordinates[0] as [number, number][],
            ),
            radius_m: radiusKm * 1000,
          }
        : null;
    return {
      geometry: finished ? (finished.geometry as GeoJSON.Geometry) : null,
      live: live ? (live.geometry as GeoJSON.Geometry) : null,
      circle,
    };
  };
  const emit = () => onChange(current());
  draw.on("finish", emit);
  draw.on("change", emit);

  return {
    begin(kind) {
      draw.clear();
      draw.setMode(MODE_OF[kind]);
      onChange(EMPTY_DRAW);
    },
    state: current,
    clear() {
      draw.clear();
      onChange(EMPTY_DRAW);
    },
    destroy() {
      draw.off("finish", emit);
      draw.off("change", emit);
      draw.stop();
    },
  };
}
