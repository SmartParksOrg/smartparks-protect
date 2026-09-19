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
import type { Bounds } from "@/components/map/fit";
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
}: {
  kind: DrawKind;
  initial?: GeoJSON.Geometry | null;
  /** Where to start looking when there is nothing to load yet: the extent of what the project
   * already has on the map, so the drawing starts over the reserve and not over a continent. */
  around?: Bounds | null;
  onChange: (geometry: GeoJSON.Geometry | null) => void;
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
  return (
    <div className="space-y-2">
      <div ref={container} className="z-0 h-72 w-full rounded-md border" />
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {kind === "point"
            ? t("Click to place the site")
            : initial
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
