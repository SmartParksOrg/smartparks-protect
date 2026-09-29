import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  Entity,
  Page as PageType,
  SeriesResponse,
} from "@/api/types";
import { SeriesChart } from "@/components/analytics/SeriesChart";
import { useMetricsByKey } from "@/hooks/useMetrics";
import { useNow } from "@/hooks/useNow";
import { browserTimezone, rangeFor, seriesLabel } from "@/lib/analytics";
import {
  inReadUnits,
  MAX_TILE_NUMBERS,
  metricRows,
  metricTileQuery,
  type MetricTileOptions,
  tileNumber,
} from "@/lib/dashboards";
import { formatAgo, formatTime, scaledUnit } from "@/lib/format";

/** The names of the subjects a tile groups by: the project's entities, or its devices. */
function useSubjectNames(
  projectId: string,
  groupBy: MetricTileOptions["group_by"],
): Map<string, string> {
  const entities = useQuery({
    queryKey: queryKeys.entities(projectId),
    queryFn: () =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { limit: 500 },
      }),
    enabled: groupBy === "entity",
  });
  const devices = useQuery({
    queryKey: queryKeys.devices({ project: projectId, tile: true }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, limit: 500 },
      }),
    enabled: groupBy === "device",
  });
  return useMemo(
    () =>
      new Map(
        (groupBy === "entity"
          ? (entities.data?.items ?? [])
          : (devices.data?.items ?? [])
        ).map((o) => [o.id, o.name]),
      ),
    [groupBy, entities.data, devices.data],
  );
}

/** Any metric of the project as a tile (decision D309): a line or bars over the period, a
 * table with a row per subject, or the latest value as a number. The tile reads the same
 * series the Data Explorer reads, so its bounds and the reader's scope hold here too. */
export function MetricTile({
  projectId,
  options,
}: {
  projectId: string;
  options: MetricTileOptions;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const registry = useMetricsByKey();
  const names = useSubjectNames(projectId, options.group_by);
  const window = useMemo(() => rangeFor(options.range), [options.range]);
  const query = useMemo(
    () => metricTileQuery(options, window),
    [options, window],
  );
  const series = useQuery({
    queryKey: queryKeys.analyticsSeries(projectId, {
      q: query,
      tile: "metric",
    }),
    queryFn: () =>
      api.get<SeriesResponse>(
        `/api/v1/projects/${projectId}/analytics/series?${query}`,
      ),
    enabled: options.metrics.length > 0,
    refetchInterval: 60_000,
  });
  const response = useMemo(
    () => (series.data ? inReadUnits(series.data) : undefined),
    [series.data],
  );
  const metricLabels = useMemo(
    () => new Map([...registry].map(([key, metric]) => [key, metric.label])),
    [registry],
  );
  const labels = useCallback(
    (index: number) =>
      response?.series?.[index]
        ? seriesLabel(response.series[index], names, metricLabels)
        : "",
    [response, names, metricLabels],
  );
  const explorer = useMemo(() => {
    const q = new URLSearchParams();
    q.set("mode", options.display === "table" ? "table" : "chart");
    for (const m of options.metrics) q.append("metric", m);
    for (const id of options.entity_ids) q.append("entity", id);
    for (const id of options.device_ids) q.append("device", id);
    q.set("range", options.range);
    return `/projects/${projectId}/analyze/explorer?${q.toString()}`;
  }, [projectId, options]);

  if (options.metrics.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        {t("This tile has no metric yet. Edit the dashboard to choose one.")}
      </p>
    );
  if (series.isError)
    return <p className="text-sm text-destructive">{series.error.message}</p>;
  const empty = series.isSuccess && (response?.series ?? []).length === 0;
  const footer = (
    <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-muted-foreground">
      <span>{(response?.notes ?? []).join(" ")}</span>
      <Link className="underline" to={explorer}>
        {t("open in Data Explorer")}
      </Link>
    </div>
  );
  if (empty)
    return (
      <div className="flex h-full flex-col justify-between">
        <p className="text-sm text-muted-foreground">
          {t("No values in this period.")}
        </p>
        {footer}
      </div>
    );

  if (options.display === "table" || options.display === "number") {
    const rows = metricRows(response, names, metricLabels, options.metrics);
    if (options.display === "number") {
      const shown = rows.slice(0, MAX_TILE_NUMBERS);
      return (
        <div className="flex h-full flex-col">
          <div className="grid flex-1 grid-cols-2 content-start gap-2 text-sm">
            {shown.map((row) => (
              <div key={row.key} className="min-w-0 rounded-md border p-2">
                <div className="truncate text-xs text-muted-foreground">
                  {row.subject}
                </div>
                <div className="text-2xl tabular-nums">
                  {tileNumber(row.last)}
                  {row.unit && (
                    <span className="ml-1 text-sm text-muted-foreground">
                      {row.unit}
                    </span>
                  )}
                </div>
                <div
                  className="text-xs text-muted-foreground"
                  title={row.lastAt ? formatTime(row.lastAt) : undefined}
                >
                  {row.lastAt ? formatAgo(row.lastAt, now) : ""}
                </div>
              </div>
            ))}
          </div>
          {rows.length > shown.length && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("{{shown}} of {{total}} shown; a table shows them all", {
                shown: shown.length,
                total: rows.length,
              })}
            </p>
          )}
          {footer}
        </div>
      );
    }
    const several = options.metrics.length > 1;
    return (
      <div className="flex h-full flex-col">
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-card text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-2 font-normal">
                  {options.group_by === "entity" ? t("Entity") : t("Device")}
                </th>
                {several && (
                  <th className="py-1 pr-2 font-normal">{t("Metric")}</th>
                )}
                <th className="py-1 pr-2 text-right font-normal">
                  {t("Latest")}
                </th>
                <th className="py-1 pr-2 font-normal">{t("When")}</th>
                <th className="py-1 pr-2 text-right font-normal">
                  {t("Mean")}
                </th>
                <th className="py-1 pr-2 text-right font-normal">
                  {t("Lowest")}
                </th>
                <th className="py-1 text-right font-normal">{t("Highest")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((row) => (
                <tr key={row.key}>
                  <td className="max-w-40 truncate py-1 pr-2">{row.subject}</td>
                  {several && (
                    <td className="max-w-40 truncate py-1 pr-2 text-muted-foreground">
                      {row.metric}
                    </td>
                  )}
                  <td className="py-1 pr-2 text-right tabular-nums whitespace-nowrap">
                    {tileNumber(row.last)}
                    {row.unit ? ` ${row.unit}` : ""}
                  </td>
                  <td
                    className="py-1 pr-2 text-xs whitespace-nowrap text-muted-foreground"
                    title={row.lastAt ? formatTime(row.lastAt) : undefined}
                  >
                    {row.lastAt ? formatAgo(row.lastAt, now) : ""}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {tileNumber(row.mean)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {tileNumber(row.min)}
                  </td>
                  <td className="py-1 text-right tabular-nums">
                    {tileNumber(row.max)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {footer}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <SeriesChart
        response={response}
        type={options.display}
        aggregate={options.aggregate}
        timezone={browserTimezone()}
        labels={labels}
        unit={
          options.metrics.length === 1
            ? scaledUnit(registry.get(options.metrics[0])?.unit).unit
            : null
        }
        className="min-h-48 flex-1"
      />
      {footer}
    </div>
  );
}
