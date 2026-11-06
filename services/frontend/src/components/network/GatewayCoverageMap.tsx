import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CoverageResponse, Gateway } from "@/api/types";
import { LoadingBar } from "@/components/common/LoadingBar";
import { periodLabel } from "@/lib/coverage";
import { basemapStyle, basemapsFor, loadBasemap } from "@/components/map/basemap";
import { type Bounds, boundsOf } from "@/components/map/fit";
import {
  ensureCoverageLayers,
  ensureEntityLayers,
  ensureGatewayLayers,
  setCoverage,
  setGateways,
} from "@/components/map/layers";
import { useMap } from "@/components/map/useMap";
import { useMapConfig } from "@/hooks/useMapConfig";
import { useTheme } from "@/hooks/useTheme";

/**
 * One gateway's coverage on a map of its own (decision D369, the gateway page's Coverage
 * tab): the positions it heard over the period, coloured by signal as the live map colours
 * them, each with the line to the gateway (decision D368), the gateway itself as its marker,
 * the view fitted to all of it.
 */
export function GatewayCoverageMap({
  projectId,
  gateway,
  hours,
}: {
  projectId: string;
  gateway: Gateway;
  hours: number;
}) {
  const { t } = useTranslation();
  const { maptilerKey } = useMapConfig();
  const basemaps = useMemo(() => basemapsFor(maptilerKey), [maptilerKey]);
  const { resolved } = useTheme();
  const container = useRef<HTMLDivElement | null>(null);
  const gatewayPoint = (gateway.geometry as { coordinates?: [number, number] } | null)
    ?.coordinates;
  const { mapRef, ready } = useMap(
    container,
    basemapStyle(loadBasemap(), basemaps, resolved === "dark"),
    gatewayPoint ?? [31.5, -24.9],
    gatewayPoint ? 11 : 5,
  );
  const params = { hours, gateway_id: [gateway.id], lines: true, zoom: 14 };
  const coverage = useQuery({
    queryKey: queryKeys.coverage(projectId, { ...params, page: "gateway" }),
    queryFn: ({ signal }) =>
      api.get<CoverageResponse>(`/api/v1/projects/${projectId}/coverage`, {
        query: params,
        signal,
      }),
    staleTime: 60_000,
  });
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureEntityLayers(map);
    ensureGatewayLayers(map);
    ensureCoverageLayers(map);
    setGateways(
      map,
      gateway.geometry
        ? [
            {
              type: "Feature",
              id: gateway.id,
              geometry: gateway.geometry as unknown as GeoJSON.Geometry,
              properties: {
                gateway_id: gateway.id,
                name: gateway.display_name,
                status: gateway.status,
              },
            },
          ]
        : [],
    );
  }, [mapRef, ready, gateway]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !coverage.data) return;
    const features = coverage.data.features as unknown as GeoJSON.Feature[];
    setCoverage(map, features);
    const positioned = features
      .filter((f) => f.geometry?.type === "Point")
      .map((f) => ({ geometry: f.geometry as { type: string; coordinates: unknown } }));
    if (gatewayPoint) positioned.push({ geometry: { type: "Point", coordinates: gatewayPoint } });
    const bounds: Bounds | null = boundsOf(positioned);
    if (bounds) map.fitBounds(bounds, { padding: 40, maxZoom: 15, duration: 0 });
  }, [mapRef, ready, coverage.data, gatewayPoint]);
  const total = coverage.data?.total ?? 0;
  const shown =
    (coverage.data?.features as unknown as GeoJSON.Feature[] | undefined)?.filter(
      (f) => f.geometry?.type === "Point",
    ).length ?? 0;
  return (
    <div className="space-y-2">
      <div className="relative h-[60vh] min-h-72 overflow-hidden rounded-lg border">
        <div ref={container} className="absolute! inset-0 z-0" />
        {coverage.isFetching && (
          <div className="absolute inset-x-0 top-0 z-10 bg-card/90 px-3 py-2">
            <LoadingBar
              label={t("Loading every position this gateway heard in the last {{period}}…", {
                period: periodLabel(hours, t),
              })}
            />
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {coverage.isError
          ? t("Could not load the heard positions: {{message}}", {
              message: coverage.error.message,
            })
          : coverage.data
            ? total === 0
              ? t("This gateway heard none of the project's devices in the period.")
              : shown < total
                ? t("{{count}} heard positions, the newest {{shown}} drawn, each with its line to the gateway", {
                    count: total,
                    shown,
                  })
                : t("{{count}} heard positions, each with its line to the gateway", {
                    count: total,
                  })
            : ""}
      </p>
    </div>
  );
}
