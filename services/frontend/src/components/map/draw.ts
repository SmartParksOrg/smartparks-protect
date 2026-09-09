import type { Map as MapLibreMap } from "maplibre-gl";
import {
  TerraDraw,
  TerraDrawLineStringMode,
  TerraDrawPointMode,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";

/**
 * Drawing on a MapLibre map with terra-draw (decision D139): one instance per map with a point,
 * a line and a polygon mode plus a select mode for vertex editing, in the brand colours.
 * Escape cancels the drawing in progress, Enter finishes it (the library's key events); a
 * finished feature can be dragged and its vertices moved, added on a midpoint or deleted.
 * The live map and the Features page share it.
 */
export type DrawKind = "point" | "line" | "polygon";

const MODE_OF: Record<DrawKind, string> = {
  point: "point",
  line: "linestring",
  polygon: "polygon",
};

export interface DrawSession {
  /** Start drawing a kind of geometry; a finished feature stays editable in select mode. */
  begin(kind: DrawKind): void;
  /** The single drawn geometry, or null while nothing is finished. */
  geometry(): GeoJSON.Geometry | null;
  /** Remove everything drawn. */
  clear(): void;
  /** Stop drawing and remove the layers. */
  destroy(): void;
}

const GREEN = "#52735E";
const LIGHT = "#90AE9B";
const SAND = "#C6B187";

export function createDrawSession(
  map: MapLibreMap,
  onChange: (geometry: GeoJSON.Geometry | null) => void,
): DrawSession {
  const draw = new TerraDraw({
    adapter: new TerraDrawMapLibreGLAdapter({ map, coordinatePrecision: 6 }),
    modes: [
      new TerraDrawPointMode({
        editable: true,
        styles: {
          pointColor: GREEN,
          pointOutlineColor: "#ffffff",
          pointOutlineWidth: 2,
          pointWidth: 7,
        },
      }),
      new TerraDrawLineStringMode({
        editable: true,
        keyEvents: { cancel: "Escape", finish: "Enter" },
        styles: {
          lineStringColor: GREEN,
          lineStringWidth: 3,
          closingPointColor: SAND,
          closingPointOutlineColor: "#ffffff",
        },
      }),
      new TerraDrawPolygonMode({
        editable: true,
        keyEvents: { cancel: "Escape", finish: "Enter" },
        styles: {
          fillColor: LIGHT,
          fillOpacity: 0.3,
          outlineColor: GREEN,
          outlineWidth: 2,
          closingPointColor: SAND,
          closingPointOutlineColor: "#ffffff",
        },
      }),
      new TerraDrawSelectMode({
        flags: {
          point: { feature: { draggable: true } },
          linestring: {
            feature: {
              draggable: true,
              coordinates: {
                midpoints: true,
                draggable: true,
                deletable: true,
              },
            },
          },
          polygon: {
            feature: {
              draggable: true,
              coordinates: {
                midpoints: true,
                draggable: true,
                deletable: true,
              },
            },
          },
        },
        styles: {
          selectedPolygonColor: LIGHT,
          selectedPolygonFillOpacity: 0.3,
          selectedPolygonOutlineColor: GREEN,
          selectedLineStringColor: GREEN,
          selectedPointColor: GREEN,
          selectionPointColor: "#ffffff",
          selectionPointOutlineColor: GREEN,
          midPointColor: SAND,
          midPointOutlineColor: "#ffffff",
        },
      }),
    ],
  });
  draw.start();

  const current = (): GeoJSON.Geometry | null => {
    const features = draw.getSnapshot();
    // the finished one, never the one still being drawn
    const done = features.filter(
      (f) =>
        !f.properties.currentlyDrawing &&
        !f.properties.midPoint &&
        !f.properties.selectionPoint,
    );
    return done.length > 0
      ? (done[done.length - 1].geometry as GeoJSON.Geometry)
      : null;
  };
  const emit = () => onChange(current());
  draw.on("finish", emit);
  draw.on("change", (_ids, type) => {
    if (type === "delete" || type === "update") emit();
  });

  return {
    begin(kind) {
      draw.clear();
      draw.setMode(MODE_OF[kind]);
      onChange(null);
    },
    geometry: current,
    clear() {
      draw.clear();
      onChange(null);
    },
    destroy() {
      draw.off("finish", emit);
      draw.stop();
    },
  };
}
