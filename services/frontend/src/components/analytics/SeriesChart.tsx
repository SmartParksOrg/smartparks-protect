import { useTranslation } from "react-i18next";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import type { SeriesResponse } from "@/api/types";
import { type ChartType, formatInZone, histogram } from "@/lib/analytics";

echarts.use([LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer]);

/** Brand palette first, then muted variants, so a chart with ten series stays readable. */
const PALETTE = ["#52735E", "#EDA08F", "#7D8FB3", "#C6B187", "#90AE9B", "#B86B5C", "#5C7FA3", "#8A7A4F", "#3E5A48", "#D8B4AA"];

interface Props {
  response: SeriesResponse | undefined;
  type: ChartType;
  aggregate: string;
  timezone: string;
  labels: (index: number) => string;
  unit?: string | null;
  className?: string;
}

/** One ECharts instance per mount; options are rebuilt when the data changes. */
export function SeriesChart({ response, type, aggregate, timezone, labels, unit, className }: Props) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const instance = echarts.init(container.current, undefined, { renderer: "canvas" });
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
    instance.setOption(buildOption(response, type, aggregate, timezone, labels, unit), true);
  }, [response, type, aggregate, timezone, labels, unit]);

  return <div ref={container} className={className ?? "h-80 w-full"} role="img" aria-label={t("Chart of the selected series")} />;
}

function buildOption(response: SeriesResponse | undefined, type: ChartType, aggregate: string, timezone: string, labels: (index: number) => string, unit?: string | null): echarts.EChartsCoreOption {
  const all = response?.series ?? [];
  const base: echarts.EChartsCoreOption = {
    color: PALETTE,
    animation: false,
    grid: { left: 56, right: 24, top: 40, bottom: 56, containLabel: false },
    legend: { type: "scroll", top: 4, textStyle: { fontSize: 11 } },
    tooltip: { trigger: type === "histogram" ? "item" : "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? `${Number.isInteger(v) ? v : v.toFixed(3)}${unit ? ` ${unit}` : ""}` : String(v ?? "")) },
  };
  if (type === "histogram") {
    const values = all.flatMap((s) => s.points.map((p) => p.values[aggregate]).filter((v): v is number => typeof v === "number"));
    const { edges, counts } = histogram(values);
    return {
      ...base,
      legend: { show: false },
      xAxis: { type: "category", data: edges.map((e) => (Number.isInteger(e) ? String(e) : e.toFixed(2))), name: unit ?? undefined },
      yAxis: { type: "value", name: "buckets" },
      series: [{ type: "bar", data: counts, name: aggregate }],
    };
  }
  const timeAxis = {
    type: "time",
    axisLabel: { formatter: (value: number) => formatInZone(new Date(value).toISOString(), timezone, { dateStyle: undefined, timeStyle: undefined, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) },
  };
  const series = all.map((s, index) => {
    const data = s.points.map((p) => [new Date(p.time).getTime(), p.values[aggregate] ?? null]);
    const name = labels(index);
    if (type === "state") return { type: "line", name, data, step: "end", showSymbol: false, areaStyle: { opacity: 0.15 } };
    if (type === "scatter") return { type: "scatter", name, data, symbolSize: 5 };
    if (type === "bar") return { type: "bar", name, data, barMaxWidth: 12 };
    return { type: "line", name, data, showSymbol: s.points.length < 60, connectNulls: false, smooth: false };
  });
  return {
    ...base,
    xAxis: timeAxis,
    yAxis: { type: "value", name: unit ?? undefined, scale: type !== "bar" },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    series,
  };
}
