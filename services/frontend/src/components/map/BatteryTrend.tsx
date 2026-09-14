import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { SeriesResponse } from "@/api/types";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";

import { useTheme } from "@/hooks/useTheme";
import { chartTheme } from "@/lib/chartStyle";
import { formatInZone } from "@/lib/analytics";
import { browserTimezone, type RangePreset, rangeFor } from "@/lib/analytics";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const RANGES: RangePreset[] = ["24h", "7d", "30d"];
const RANGE_LABELS: Record<string, string> = {
  "24h": "24 h",
  "7d": "7 d",
  "30d": "30 d",
};

/** The battery value of an entity or device panel as a button that unfolds the recent trend
 * inside the panel (Tim, 2026-09-14): a small line of the collar's battery voltage over the
 * last day, week or month from the analytics series, so a person sees whether it drops
 * without leaving the map or covering it. */
export function BatteryValue({
  deviceId,
  voltage,
  open,
  onToggle,
  className,
}: {
  deviceId: string | null | undefined;
  voltage: number;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const label = `${voltage.toFixed(2)} V`;
  if (!deviceId) return <span className={className}>{label}</span>;
  return (
    <button
      type="button"
      className={`underline underline-offset-2 hover:text-primary ${className ?? ""}`}
      title={open ? t("Hide the battery trend") : t("Show the battery trend")}
      aria-expanded={open}
      onClick={onToggle}
    >
      {label}
    </button>
  );
}

/** The trend itself: mounted while the popover is open, so the series is read on demand. */
export function BatteryTrend({
  projectId,
  deviceId,
}: {
  projectId: string;
  deviceId: string;
}) {
  const { t } = useTranslation();
  const [range, setRange] = useState<RangePreset>("7d");
  const window = rangeFor(range);
  const timezone = browserTimezone();
  const series = useQuery({
    queryKey: queryKeys.analyticsSeries(projectId, {
      metric: "battery_voltage",
      deviceId,
      ...window,
    }),
    queryFn: () =>
      api.get<SeriesResponse>(
        `/api/v1/projects/${projectId}/analytics/series`,
        {
          query: {
            metric: "battery_voltage",
            device_id: deviceId,
            from: window.from,
            to: window.to,
            agg: "mean",
            group_by: "device",
            layout: "series",
          },
        },
      ),
    staleTime: 60_000,
  });
  const points = series.data?.series?.[0]?.points ?? [];
  const values = points
    .map((p) => p.values.mean)
    .filter((v): v is number => v != null);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{t("Battery")}</span>
        <span className="flex gap-1" role="group" aria-label={t("Period")}>
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              className={`rounded px-1.5 py-0.5 text-xs ${r === range ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}
              aria-pressed={r === range}
              onClick={() => setRange(r)}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </span>
      </div>
      {series.isPending ? (
        <div className="h-28 text-xs text-muted-foreground">
          {t("Loading…")}
        </div>
      ) : series.isError ? (
        <div className="h-24 text-xs text-destructive">
          {series.error.message}
        </div>
      ) : values.length === 0 ? (
        <div className="flex h-24 items-center text-xs text-muted-foreground">
          {t("No readings in this period.")}
        </div>
      ) : (
        <>
          <Sparkline
            points={points.map(
              (p) =>
                [Date.parse(p.time), p.values.mean] as [number, number | null],
            )}
            timezone={timezone}
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>
              {t("Low {{value}} V", { value: Math.min(...values).toFixed(2) })}
            </span>
            <span>
              {t("High {{value}} V", { value: Math.max(...values).toFixed(2) })}
            </span>
            <span>
              {t("Now {{value}} V", {
                value: values[values.length - 1].toFixed(2),
              })}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

/** A small line of one series (decision-free: brand green, no legend, no zoom, two y labels,
 * a few time labels), sized for a popover. */
function Sparkline({
  points,
  timezone,
}: {
  points: [number, number | null][];
  timezone: string;
}) {
  const { t } = useTranslation();
  const { resolved } = useTheme();
  const dark = resolved === "dark";
  const container = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!container.current) return;
    const instance = echarts.init(container.current, undefined, {
      renderer: "canvas",
    });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    const th = chartTheme(dark);
    const values = points
      .map((p) => p[1])
      .filter((v): v is number => v != null);
    // the axis in 0.05 V steps around the data, so the labels never crowd
    const step = 0.05;
    const low = Math.floor((Math.min(...values) - 0.01) / step) * step;
    const high = Math.ceil((Math.max(...values) + 0.01) / step) * step;
    instance.setOption(
      {
        animation: false,
        grid: { left: 36, right: 8, top: 6, bottom: 18 },
        tooltip: {
          trigger: "axis",
          backgroundColor: th.tooltipBg,
          textStyle: { color: th.tooltipText, fontSize: 11 },
          formatter: (params: unknown) => {
            const p = (params as { value: [number, number | null] }[])[0];
            if (!p) return "";
            return `${formatInZone(new Date(p.value[0]).toISOString(), timezone)}<br/>${p.value[1] == null ? "" : p.value[1].toFixed(2)} V`;
          },
        },
        xAxis: {
          type: "time",
          axisLine: { lineStyle: { color: th.grid } },
          axisTick: { show: false },
          axisLabel: {
            color: th.text,
            fontSize: 10,
            hideOverlap: true,
            margin: 6,
          },
          splitLine: { show: false },
        },
        yAxis: {
          type: "value",
          min: Number(low.toFixed(2)),
          max: Number(high.toFixed(2)),
          interval: Math.max(step, Math.round((high - low) / 2 / step) * step),
          axisLabel: {
            color: th.text,
            fontSize: 10,
            formatter: (v: number) => v.toFixed(2),
          },
          splitLine: { lineStyle: { color: th.grid } },
        },
        series: [
          {
            type: "line",
            data: points,
            showSymbol: false,
            connectNulls: true,
            lineStyle: { width: 1.5, color: "#52735E" },
            areaStyle: { color: "#52735E", opacity: 0.12 },
            itemStyle: { color: "#52735E" },
          },
        ],
      },
      true,
    );
  }, [points, timezone, dark]);
  return (
    <div
      ref={container}
      className="h-28 w-full"
      role="img"
      aria-label={t("Battery voltage over the period")}
    />
  );
}
