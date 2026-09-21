import { useTranslation } from "react-i18next";
import { useEffect, useRef } from "react";

import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import {
  createDrawSession,
  type DrawKind,
  type DrawSession,
} from "@/components/map/draw";
import { geometryBounds, type Bounds } from "@/components/map/fit";
import {
  ensureGhostLayers,
  setGhosts,
  type ProposedArea,
} from "@/components/map/propose";
import { useMap } from "@/components/map/useMap";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";

/** Where to start looking: the middle of the shape being corrected, else the reserve. */
function centreOf(
  geometry: GeoJSON.Geometry | null | undefined,
): [number, number] | null {
  if (!geometry) return null;
  const points: number[][] =
    geometry.type === "Point"
      ? [geometry.coordinates]
      : geometry.type === "LineString"
        ? geometry.coordinates
        : geometry.type === "Polygon"
          ? geometry.coordinates[0]
          : [];
  if (points.length === 0) return null;
  return [
    points.reduce((s, p) => s + p[0], 0) / points.length,
    points.reduce((s, p) => s + p[1], 0) / points.length,
  ];
}

/**
 * The drawing map of a feature dialog: the shared terra-draw session (decision D139), the
 * kind following the feature type. Sites are a single point, routes and fence lines a line,
 * the rest a polygon. With `initial` it starts from that shape, selected, so a line can be
 * corrected instead of drawn again (phase 32).
 */
export function DrawMap({
  kind,
  initial = null,
  around = null,
  onChange,
  proposing = false,
  onProposeAt,
  ghosts = [],
  load = null,
  onView,
}: {
  kind: DrawKind;
  initial?: GeoJSON.Geometry | null;
  /** Where to start looking when there is nothing to load yet: the extent of what the project
   * already has on the map, so the drawing starts over the reserve and not over a continent. */
  around?: Bounds | null;
  onChange: (geometry: GeoJSON.Geometry | null) => void;
  /** Propose mode (phase 33): the drawing rests, the pointer is a crosshair and a click on
   * the map reports its place instead of adding a vertex. */
  proposing?: boolean;
  onProposeAt?: (lonLat: [number, number]) => void;
  /** The candidates drawn as faint outlines while the person chooses. */
  ghosts?: ProposedArea[];
  /** A shape to put in the editor, selected: the candidate chosen. A new object loads again. */
  load?: { geometry: GeoJSON.Geometry } | null;
  /** What the map shows, at the start and after every move: the box a search by name reads. */
  onView?: (bounds: Bounds) => void;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const { resolved: resolvedTheme } = useTheme();
  const centre = centreOf(initial);
  const { mapRef, ready } = useMap(
    container,
    basemapStyle(loadBasemap(), basemapsFor(null), resolvedTheme === "dark"),
    centre ?? [31.5, -24.9],
    centre ? 13 : 6,
  );
  const session = useRef<DrawSession | null>(null);
  const initialRef = useRef(initial);
  const aroundRef = useRef(around);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || initialRef.current || !aroundRef.current) return;
    map.fitBounds(aroundRef.current, { padding: 40, duration: 0, maxZoom: 14 });
  }, [mapRef, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const s = createDrawSession(map, (state) => onChange(state.geometry));
    session.current = s;
    if (initialRef.current) s.load(kind, initialRef.current);
    else s.begin(kind);
    return () => {
      s.destroy();
      session.current = null;
    };
  }, [mapRef, ready, kind, onChange]);
  // propose mode: the session rests and the map's own click reports where
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !proposing) return;
    session.current?.idle();
    map.getCanvas().style.cursor = "crosshair";
    const onClick = (e: { lngLat: { lng: number; lat: number } }) =>
      onProposeAt?.([e.lngLat.lng, e.lngLat.lat]);
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
      map.getCanvas().style.cursor = "";
    };
  }, [mapRef, ready, proposing, onProposeAt]);
  const onViewRef = useRef(onView);
  useEffect(() => {
    onViewRef.current = onView;
  }, [onView]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const report = () => {
      const view = map.getBounds();
      onViewRef.current?.([
        [view.getWest(), view.getSouth()],
        [view.getEast(), view.getNorth()],
      ]);
    };
    report();
    map.on("moveend", report);
    return () => {
      map.off("moveend", report);
    };
  }, [mapRef, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureGhostLayers(map);
    setGhosts(map, ghosts);
  }, [mapRef, ready, ghosts]);
  // the chosen candidate goes into the editor and the map goes to it
  useEffect(() => {
    const map = mapRef.current;
    if (!load || !session.current || !map) return;
    session.current.load(kind, load.geometry);
    const bounds = geometryBounds([{ geometry: load.geometry as never }]);
    if (bounds)
      map.fitBounds(bounds, { padding: 40, duration: 300, maxZoom: 16 });
  }, [mapRef, load, kind]);
  return (
    <div className="space-y-2">
      <div ref={container} className="z-0 h-72 w-full rounded-md border" />
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {proposing
            ? t(
                "Click inside the area you want; the roads, rivers and areas around it decide the shape",
              )
            : kind === "point"
              ? t("Click to place the site")
              : initial || load
                ? t(
                    "Drag a vertex to move it, a midpoint to add one; Delete removes a vertex",
                  )
                : t(
                    "Click to add vertices, click the last one again or press Enter to finish",
                  )}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            session.current?.clear();
            session.current?.begin(kind);
          }}
        >
          {t("Clear")}
        </Button>
      </div>
    </div>
  );
}
