import type { MapLayerMouseEvent } from "maplibre-gl";
import { useTranslation } from "react-i18next";
import { Maximize2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Feature } from "@/api/types";
import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import {
  bindTrackPointClicks,
  ensureEntityLayers,
  ensureFeatureLayers,
  ensureTrackLayers,
  setFeatures,
  setTracks,
  type TrackLayer,
  trackPointKey,
} from "@/components/map/layers";
import { useMap } from "@/components/map/useMap";
import { Button } from "@/components/ui/button";
import { useMapConfig } from "@/hooks/useMapConfig";
import { formatInZone } from "@/lib/analytics";
import { boundsOfTracks, pointsAt } from "@/lib/explore";

/**
 * The map of the Explore canvas (decision D153): the tracks of the selection over its period
 * with the project's features, a time slider that moves the marked moment along the tracks, and
 * the point of every track at that moment ringed. Hovering a track point marks its moment in
 * the other views; a click pins it.
 */
export function ExploreMap({
  tracks,
  features,
  window,
  timezone,
  marked,
  fitKey,
  onHover,
  onPick,
}: {
  tracks: TrackLayer[];
  features: Feature[];
  window: { from: string; to: string };
  timezone: string;
  marked: number | null;
  /** Changes when the selection changes: the map fits the tracks again. */
  fitKey: string;
  onHover: (ms: number | null) => void;
  onPick: (ms: number) => void;
}) {
  const { t } = useTranslation();
  const { maptilerKey } = useMapConfig();
  const basemaps = useMemo(() => basemapsFor(maptilerKey), [maptilerKey]);
  const container = useRef<HTMLDivElement | null>(null);
  const { mapRef, ready } = useMap(
    container,
    basemapStyle(loadBasemap(), basemaps),
    [31.5, -24.9],
    6,
  );
  const handlers = useRef({ onHover, onPick });
  useEffect(() => {
    handlers.current = { onHover, onPick };
  }, [onHover, onPick]);

  useEffect(() => {
    const map = mapRef.current;
    const element = container.current;
    if (!map || !ready || !element) return;
    // the canvas takes the page's height after the first paint: follow the container
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(element);
    ensureEntityLayers(map);
    ensureFeatureLayers(map);
    ensureTrackLayers(map);
    const unbind = bindTrackPointClicks(map, (props) =>
      handlers.current.onPick(Date.parse(props.time)),
    );
    const onMove = (e: MapLayerMouseEvent) => {
      const time = e.features?.[0]?.properties?.time;
      if (typeof time === "string") handlers.current.onHover(Date.parse(time));
    };
    const onLeave = () => handlers.current.onHover(null);
    map.on("mousemove", "track-points", onMove);
    map.on("mouseleave", "track-points", onLeave);
    return () => {
      observer.disconnect();
      unbind();
      map.off("mousemove", "track-points", onMove);
      map.off("mouseleave", "track-points", onLeave);
    };
  }, [mapRef, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setFeatures(
      map,
      features
        .filter((f) => f.geometry)
        .map((f) => ({
          type: "Feature",
          geometry: f.geometry as unknown as GeoJSON.Geometry,
          properties: { id: f.id, name: f.name, feature_type: f.feature_type },
        })),
    );
  }, [mapRef, ready, features]);

  const fitted = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setTracks(map, tracks);
    const bounds = boundsOfTracks(tracks);
    if (bounds && fitted.current !== fitKey) {
      fitted.current = fitKey;
      map.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 0 });
    }
  }, [mapRef, ready, tracks, fitKey]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("track-point-selected")) return;
    const keys =
      marked === null
        ? []
        : pointsAt(tracks, marked).map((p) => trackPointKey(p.ownerId, p.time));
    map.setFilter("track-point-selected", [
      "in",
      ["get", "key"],
      ["literal", keys],
    ]);
  }, [mapRef, ready, tracks, marked]);

  const from = Date.parse(window.from);
  const to = Date.parse(window.to);
  const [sliding, setSliding] = useState<number | null>(null);
  const value = sliding ?? marked ?? to;
  const fit = () => {
    const map = mapRef.current;
    const bounds = boundsOfTracks(tracks);
    if (map && bounds) map.fitBounds(bounds, { padding: 48, maxZoom: 14 });
  };

  return (
    <div className="absolute inset-0">
      <div ref={container} className="absolute! inset-0 z-0" />
      <div className="pointer-events-none absolute top-3 left-3 z-10 flex gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="pointer-events-auto h-8 bg-card"
          onClick={fit}
          disabled={tracks.length === 0}
        >
          <Maximize2 className="size-4" /> {t("Fit the tracks")}
        </Button>
      </div>
      {/* the time slider (decision D153): its moment is the marked one, released it pins */}
      <div className="absolute right-14 bottom-3 left-3 z-10 flex items-center gap-3 rounded-md border bg-card/95 px-3 py-2 text-xs shadow">
        <span className="hidden whitespace-nowrap text-muted-foreground sm:inline">
          {formatInZone(window.from, timezone)}
        </span>
        <input
          type="range"
          aria-label={t("Moment on the tracks")}
          className="min-w-0 flex-1 accent-primary"
          min={from}
          max={to}
          step={60_000}
          value={Math.min(to, Math.max(from, value))}
          onChange={(e) => {
            const ms = Number(e.target.value);
            setSliding(ms);
            onHover(ms);
          }}
          onPointerUp={() => {
            if (sliding !== null) onPick(sliding);
            setSliding(null);
          }}
          onKeyUp={() => {
            if (sliding !== null) onPick(sliding);
            setSliding(null);
          }}
        />
        <span className="whitespace-nowrap font-medium">
          {formatInZone(new Date(value).toISOString(), timezone)}
        </span>
      </div>
    </div>
  );
}
