import { useTranslation } from "react-i18next";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Compass,
  Layers,
  Maximize,
  Maximize2,
  Minimize,
  Minus,
  Mountain,
  Plus,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Track } from "@/api/types";
import {
  ANALYSIS_KINDS,
  INTENSITY_RAMP,
  bindAnalysisClicks,
  boundsOfFeatures,
  decorateAnalysisFeatures,
  ensureAnalysisLayers,
  ensureIntensityLayers,
  setAnalysisFeatures,
  setAnalysisKinds,
  setIntensityFeatures,
  setIntensityVisible,
  setTracksVisible,
} from "@/components/map/analysisLayers";
import {
  type BasemapKey,
  basemapsFor,
  basemapStyle,
  loadBasemap,
  saveBasemap,
} from "@/components/map/basemap";
import { ControlStrip, type StripItem } from "@/components/map/ControlStrip";
import {
  TERRAIN_PITCH,
  setTerrain,
  terrainTileJson,
} from "@/components/map/terrain";
import {
  ensureEntityLayers,
  ensureHeatLayer,
  ensureTrackLayers,
  setHeatPaint,
  setHeatPoints,
  setTracks,
  type TrackLayer,
} from "@/components/map/layers";
import { useMap } from "@/components/map/useMap";
import { useMapConfig } from "@/hooks/useMapConfig";
import { usePreference } from "@/hooks/usePreference";
import { useTheme } from "@/hooks/useTheme";
import { boundsOfTracks } from "@/lib/explore";
import {
  intensityFeatures,
  subjectColor,
  type ResultDocument,
} from "@/lib/analyses";

const TRACK_POINTS = 5000;
const HEAT_RADIUS_M = 60;
const HEAT_SENSITIVITY = 2;
const trackData = (results: { data?: Track }[]): (Track | undefined)[] =>
  results.map((r) => r.data);

/**
 * The map of an analysis result (plan, section 8.5): the subjects' tracks over the main
 * period and the result polygons by kind, each toggled by a chip; a click on a polygon
 * shows its label, its area and its share.
 */
export function ResultMap({
  projectId,
  runId,
  document,
  labels,
  tracksOn = true,
}: {
  projectId: string;
  runId: string;
  document: ResultDocument;
  labels: Record<string, string>;
  /** Whether the subjects' tracks start shown; a use map reads better without them. */
  tracksOn?: boolean;
}) {
  const { t } = useTranslation();
  const { maptilerKey } = useMapConfig();
  const basemaps = useMemo(() => basemapsFor(maptilerKey), [maptilerKey]);
  const container = useRef<HTMLDivElement | null>(null);
  const frame = useRef<HTMLDivElement | null>(null);
  const { resolved } = useTheme();
  // the same base map, terrain and full screen controls as the live map, in its strips
  const [basemap, setBasemap] = useState<BasemapKey>(loadBasemap);
  const [terrainOn, setTerrainOn] = usePreference<boolean>("terrain", false);
  const [fullscreen, setFullscreen] = useState(false);
  const { mapRef, ready, stripHost, zoomHost } = useMap(
    container,
    basemapStyle(basemap, basemaps, resolved === "dark"),
    [31.5, -24.9],
    6,
  );
  const main = document.periods.find((p) => p.key === "main");
  const available = ANALYSIS_KINDS.filter((k) => document.geometries[k]);
  const [hidden, setHidden] = useState<string[]>(() => {
    const off: string[] = tracksOn
      ? ["points", "heatmap"]
      : ["tracks", "points", "heatmap"];
    // the hotspot outlines repeat what the intensity cells show; start folded away
    if (document.summary.intensity) off.push("hotspot");
    return off;
  });
  const [picked, setPicked] = useState<Record<string, unknown> | null>(null);
  const shown = available.filter((k) => !hidden.includes(k));
  const intensity = useMemo(() => intensityFeatures(document), [document]);
  const toggles: string[] = [
    ...(intensity.length ? ["intensity"] : []),
    ...available,
    "tracks",
    "points",
    "heatmap",
  ];

  const tracks = useQueries({
    queries: document.subjects.map((subject) => ({
      queryKey: queryKeys.track(projectId, {
        entity_id: subject.id,
        from: main?.time_from,
        to: main?.time_to,
        max_points: TRACK_POINTS,
      }),
      queryFn: () =>
        api.get<Track>(`/api/v1/projects/${projectId}/tracks`, {
          query: {
            entity_id: subject.id,
            from: main?.time_from,
            to: main?.time_to,
            max_points: TRACK_POINTS,
          },
        }),
      enabled: Boolean(main),
      staleTime: 5 * 60_000,
    })),
    combine: trackData,
  });
  const trackLayers = useMemo<TrackLayer[]>(
    () =>
      tracks.flatMap((track, i) =>
        track && track.returned_points > 0
          ? [
              {
                entityId: document.subjects[i].id,
                kind: "entity" as const,
                geometry: track.geometry as unknown as GeoJSON.Geometry,
                times: track.times,
              },
            ]
          : [],
      ),
    [tracks, document.subjects],
  );
  // the fixes as points, for the points layer and the heatmap
  const pointFeatures = useMemo<GeoJSON.Feature[]>(
    () =>
      trackLayers.flatMap((track) => {
        const coords =
          track.geometry.type === "LineString"
            ? track.geometry.coordinates
            : track.geometry.type === "MultiPoint"
              ? track.geometry.coordinates
              : [];
        return coords.map((c) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: c },
          properties: { entity_id: track.entityId },
        }));
      }),
    [trackLayers],
  );
  const geometries = useQuery({
    queryKey: queryKeys.analysisGeometries(projectId, runId, { limit: 2000 }),
    queryFn: () =>
      api.get<GeoJSON.FeatureCollection>(
        `/api/v1/projects/${projectId}/analyses/${runId}/geometries`,
        { query: { limit: 2000 } },
      ),
    enabled: available.length > 0,
    staleTime: Infinity,
  });
  const features = useMemo(
    () =>
      decorateAnalysisFeatures(geometries.data?.features ?? [], (id) =>
        id ? subjectColor(id) : "#52735E",
      ),
    [geometries.data],
  );

  useEffect(() => {
    const map = mapRef.current;
    const element = container.current;
    if (!map || !ready || !element) return;
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(element);
    ensureEntityLayers(map);
    ensureTrackLayers(map);
    // the line says where the animal went; the live map's point markers would hide the polygons
    if (map.getLayer("track-points"))
      map.setLayoutProperty("track-points", "visibility", "none");
    ensureAnalysisLayers(map);
    ensureIntensityLayers(map);
    ensureHeatLayer(map);
    // a result holds a period of fixes in a small area: a tight radius and the lowest
    // sensitivity keep the heatmap graded instead of one saturated blob
    const paintHeat = () =>
      setHeatPaint(map, HEAT_RADIUS_M, map.getCenter().lat, HEAT_SENSITIVITY);
    paintHeat();
    map.on("moveend", paintHeat);
    const unbind = bindAnalysisClicks(map, setPicked);
    return () => {
      observer.disconnect();
      unbind();
      map.off("moveend", paintHeat);
    };
  }, [mapRef, ready]);

  // terrain on top of any base map; a style change drops it, so it is applied again on ready
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setTerrain(
      map,
      terrainOn && maptilerKey ? terrainTileJson(maptilerKey) : null,
    );
  }, [mapRef, ready, terrainOn, maptilerKey]);

  // full screen through the browser's API on the map's frame; the map follows the size
  useEffect(() => {
    const onChange = () => {
      setFullscreen(globalThis.document.fullscreenElement === frame.current);
      setTimeout(() => mapRef.current?.resize(), 50);
    };
    globalThis.document.addEventListener("fullscreenchange", onChange);
    return () =>
      globalThis.document.removeEventListener("fullscreenchange", onChange);
  }, [mapRef]);
  const toggleFullscreen = () => {
    if (globalThis.document.fullscreenElement)
      void globalThis.document.exitFullscreen();
    else void frame.current?.requestFullscreen?.();
  };

  const fitted = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setTracks(map, trackLayers);
    setAnalysisFeatures(map, features);
    setIntensityFeatures(map, intensity);
    setHeatPoints(map, pointFeatures);
    if (fitted.current || (available.length > 0 && features.length === 0))
      return;
    // the polygons say where the result is; a track may hold a far outlier
    const bounds = boundsOfFeatures(features) ?? boundsOfTracks(trackLayers);
    if (bounds) {
      fitted.current = true;
      map.fitBounds(bounds, { padding: 40, maxZoom: 14, duration: 0 });
    }
  }, [
    mapRef,
    ready,
    trackLayers,
    pointFeatures,
    features,
    intensity,
    available.length,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setAnalysisKinds(map, shown);
    setIntensityVisible(map, !hidden.includes("intensity"));
    setTracksVisible(map, !hidden.includes("tracks"));
    if (map.getLayer("track-points"))
      map.setLayoutProperty(
        "track-points",
        "visibility",
        hidden.includes("points") ? "none" : "visible",
      );
    if (map.getLayer("heat"))
      map.setLayoutProperty(
        "heat",
        "visibility",
        hidden.includes("heatmap") ? "none" : "visible",
      );
    // the list is derived from the document and the hidden set
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapRef, ready, shown.join(","), hidden.join(",")]);

  const fit = () => {
    const map = mapRef.current;
    const bounds = boundsOfFeatures(features) ?? boundsOfTracks(trackLayers);
    if (map && bounds) map.fitBounds(bounds, { padding: 40, maxZoom: 14 });
  };
  const toolItems: StripItem[] = [
    {
      kind: "menu",
      key: "basemap",
      icon: Layers,
      label: t("Base map"),
      value: basemap,
      options: Object.entries(basemaps).map(([value, b]) => ({
        value,
        label: b.label,
      })),
      onChange: (v) => {
        setBasemap(v as BasemapKey);
        saveBasemap(v as BasemapKey);
      },
    },
    ...(maptilerKey
      ? [
          {
            key: "terrain",
            icon: Mountain,
            label: terrainOn ? t("Flat map") : t("3D terrain"),
            active: terrainOn,
            onClick: () => {
              const next = !terrainOn;
              setTerrainOn(next);
              mapRef.current?.easeTo({
                pitch: next ? TERRAIN_PITCH : 0,
                duration: 600,
              });
            },
          } satisfies StripItem,
        ]
      : []),
    {
      key: "fullscreen",
      icon: fullscreen ? Minimize : Maximize,
      label: fullscreen ? t("Leave full screen") : t("Full screen"),
      active: fullscreen,
      onClick: toggleFullscreen,
    },
  ];
  const zoomItems: StripItem[] = [
    {
      key: "zoom-in",
      icon: Plus,
      label: t("Zoom in"),
      onClick: () => mapRef.current?.zoomIn(),
    },
    {
      key: "zoom-out",
      icon: Minus,
      label: t("Zoom out"),
      onClick: () => mapRef.current?.zoomOut(),
    },
    {
      key: "north",
      icon: Compass,
      label: t("Reset north"),
      onClick: () => mapRef.current?.easeTo({ bearing: 0, pitch: 0 }),
    },
    {
      key: "fit",
      icon: Maximize2,
      label: t("Fit the result"),
      disabled: trackLayers.length === 0 && features.length === 0,
      onClick: fit,
    },
  ];
  const kindLabel: Record<string, string> = {
    intensity: t("Use intensity"),
    tracks: t("Tracks"),
    points: t("Fixes"),
    heatmap: t("Heatmap"),
    area: t("Areas by pressure"),
    mcp: t("MCP 95%"),
    kde: t("KDE 50% and 95%"),
    hotspot: t("Hotspots"),
    cluster: t("Clusters"),
  };
  const area =
    typeof picked?.hectares === "number"
      ? picked.hectares
      : typeof picked?.area_m2 === "number"
        ? picked.area_m2 / 10_000
        : null;
  const share =
    typeof picked?.time_share === "number"
      ? picked.time_share
      : typeof picked?.fix_share === "number"
        ? picked.fix_share
        : null;
  return (
    <div
      ref={frame}
      className={`relative overflow-hidden rounded-md border bg-card ${fullscreen ? "" : "h-80 lg:h-[26rem]"}`}
    >
      <div ref={container} className="absolute! inset-0 z-0" />
      {stripHost && createPortal(<ControlStrip items={toolItems} />, stripHost)}
      {zoomHost &&
        createPortal(
          <ControlStrip items={zoomItems} label={t("Zoom and position")} />,
          zoomHost,
        )}
      <div className="pointer-events-none absolute top-2 right-14 left-2 z-10 flex flex-wrap items-center gap-1.5">
        {toggles.map((kind) => (
          <button
            key={kind}
            type="button"
            className={`pointer-events-auto rounded-full border px-2 py-0.5 text-xs shadow ${
              !hidden.includes(kind)
                ? "bg-card text-foreground"
                : "bg-card/70 text-muted-foreground line-through"
            }`}
            aria-pressed={!hidden.includes(kind)}
            onClick={() =>
              setHidden((h) =>
                h.includes(kind) ? h.filter((k) => k !== kind) : [...h, kind],
              )
            }
          >
            {kindLabel[kind] ?? kind}
          </button>
        ))}
      </div>
      {intensity.length > 0 && !hidden.includes("intensity") && (
        <div className="pointer-events-none absolute right-2 bottom-2 z-10 flex items-center gap-1 rounded-md border bg-card/95 px-2 py-1 text-[10px] text-muted-foreground shadow">
          <span>{t("less use")}</span>
          {INTENSITY_RAMP.map((c) => (
            <span
              key={c}
              className="inline-block size-3"
              style={{ backgroundColor: c }}
            />
          ))}
          <span>{t("more")}</span>
        </div>
      )}
      {picked && (
        <div className="absolute bottom-2 left-2 z-10 max-w-[80%] rounded-md border bg-card/95 px-3 py-2 text-xs shadow">
          <div className="flex items-start justify-between gap-3">
            <p className="font-medium">{String(picked.label ?? "")}</p>
            <button
              type="button"
              className="text-muted-foreground"
              onClick={() => setPicked(null)}
              aria-label={t("Close")}
            >
              ×
            </button>
          </div>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-muted-foreground">
            {area !== null && (
              <>
                <dt>{t("Area")}</dt>
                <dd>{t("{{value}} ha", { value: area.toFixed(1) })}</dd>
              </>
            )}
            {share !== null && (
              <>
                <dt>
                  {typeof picked.time_share === "number"
                    ? t("Time share")
                    : t("Fix share")}
                </dt>
                <dd>{Math.round(share * 100)}%</dd>
              </>
            )}
            {typeof picked.relative_pressure === "number" && (
              <>
                <dt>{t("Relative pressure")}</dt>
                <dd>
                  {picked.relative_pressure.toFixed(2)}
                  {typeof picked.pressure_rank === "number" &&
                    ` (#${picked.pressure_rank})`}
                </dd>
              </>
            )}
            {typeof picked.animal_days_per_ha === "number" && (
              <>
                <dt>{t("Use")}</dt>
                <dd>
                  {t("{{value}} animal-days per ha", {
                    value: picked.animal_days_per_ha.toFixed(3),
                  })}
                </dd>
              </>
            )}
            {typeof picked.rest_days === "number" && (
              <>
                <dt>{t("Rest days")}</dt>
                <dd>{picked.rest_days}</dd>
              </>
            )}
            {typeof picked.visits === "number" && (
              <>
                <dt>{t("Visits")}</dt>
                <dd>{picked.visits}</dd>
              </>
            )}
            {typeof picked.period === "string" && (
              <>
                <dt>{t("Period")}</dt>
                <dd>{labels[picked.period] ?? picked.period}</dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}
