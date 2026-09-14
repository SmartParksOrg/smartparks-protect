import { useTranslation } from "react-i18next";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Maximize2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Track } from "@/api/types";
import {
  ANALYSIS_KINDS,
  bindAnalysisClicks,
  boundsOfFeatures,
  decorateAnalysisFeatures,
  ensureAnalysisLayers,
  setAnalysisFeatures,
  setAnalysisKinds,
} from "@/components/map/analysisLayers";
import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import {
  ensureEntityLayers,
  ensureTrackLayers,
  setTracks,
  type TrackLayer,
} from "@/components/map/layers";
import { useMap } from "@/components/map/useMap";
import { Button } from "@/components/ui/button";
import { useMapConfig } from "@/hooks/useMapConfig";
import { useTheme } from "@/hooks/useTheme";
import { boundsOfTracks } from "@/lib/explore";
import { subjectColor, type ResultDocument } from "@/lib/analyses";

const TRACK_POINTS = 5000;
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
}: {
  projectId: string;
  runId: string;
  document: ResultDocument;
  labels: Record<string, string>;
}) {
  const { t } = useTranslation();
  const { maptilerKey } = useMapConfig();
  const basemaps = useMemo(() => basemapsFor(maptilerKey), [maptilerKey]);
  const container = useRef<HTMLDivElement | null>(null);
  const { resolved } = useTheme();
  const { mapRef, ready } = useMap(
    container,
    basemapStyle(loadBasemap(), basemaps, resolved === "dark"),
    [31.5, -24.9],
    6,
  );
  const main = document.periods.find((p) => p.key === "main");
  const available = ANALYSIS_KINDS.filter((k) => document.geometries[k]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [picked, setPicked] = useState<Record<string, unknown> | null>(null);
  const shown = available.filter((k) => !hidden.includes(k));

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
    ensureAnalysisLayers(map);
    const unbind = bindAnalysisClicks(map, setPicked);
    return () => {
      observer.disconnect();
      unbind();
    };
  }, [mapRef, ready]);

  const fitted = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setTracks(map, trackLayers);
    setAnalysisFeatures(map, features);
    if (fitted.current) return;
    const bounds = boundsOfTracks(trackLayers) ?? boundsOfFeatures(features);
    if (bounds) {
      fitted.current = true;
      map.fitBounds(bounds, { padding: 40, maxZoom: 14, duration: 0 });
    }
  }, [mapRef, ready, trackLayers, features]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setAnalysisKinds(map, shown);
    // the list is derived from the document and the hidden set
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapRef, ready, shown.join(",")]);

  const fit = () => {
    const map = mapRef.current;
    const bounds = boundsOfTracks(trackLayers) ?? boundsOfFeatures(features);
    if (map && bounds) map.fitBounds(bounds, { padding: 40, maxZoom: 14 });
  };
  const kindLabel: Record<string, string> = {
    mcp: t("MCP 95%"),
    kde: t("KDE 50% and 95%"),
    hotspot: t("Hotspots"),
    cluster: t("Clusters"),
  };
  const area =
    typeof picked?.area_m2 === "number" ? picked.area_m2 / 10_000 : null;
  const share =
    typeof picked?.time_share === "number"
      ? picked.time_share
      : typeof picked?.fix_share === "number"
        ? picked.fix_share
        : null;
  return (
    <div className="relative h-80 overflow-hidden rounded-md border lg:h-[26rem]">
      <div ref={container} className="absolute! inset-0 z-0" />
      <div className="pointer-events-none absolute top-2 right-2 left-2 z-10 flex flex-wrap items-center gap-1.5">
        {available.map((kind) => (
          <button
            key={kind}
            type="button"
            className={`pointer-events-auto rounded-full border px-2 py-0.5 text-xs shadow ${
              shown.includes(kind)
                ? "bg-card text-foreground"
                : "bg-card/70 text-muted-foreground line-through"
            }`}
            aria-pressed={shown.includes(kind)}
            onClick={() =>
              setHidden((h) =>
                h.includes(kind) ? h.filter((k) => k !== kind) : [...h, kind],
              )
            }
          >
            {kindLabel[kind] ?? kind}
          </button>
        ))}
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="pointer-events-auto ml-auto h-7 bg-card"
          onClick={fit}
          disabled={trackLayers.length === 0 && features.length === 0}
        >
          <Maximize2 className="size-4" /> {t("Fit")}
        </Button>
      </div>
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
