import { useTranslation } from "react-i18next";
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  PolarComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { useTheme } from "@/hooks/useTheme";
import type {
  ResultChart as ResultChartData,
  ResultChartSeries,
} from "@/lib/analyses";
import { PALETTE, chartTheme } from "@/lib/chartStyle";

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  PolarComponent,
  CanvasRenderer,
]);

/** A chart of a result document: a line or bar over time, a stacked bar, or a rose of
 * directions; the data comes from the document, the look from the brand palette. */
export function ResultChart({
  chart,
  labels,
  colorOf,
  className,
}: {
  chart: ResultChartData;
  labels?: Record<string, string>;
  /** The colour of a series, or null for the palette's; a subject keeps its map colour. */
  colorOf?: (series: ResultChartSeries) => string | null;
  className?: string;
}) {
  const { t } = useTranslation();
  const { resolved } = useTheme();
  const dark = resolved === "dark";
  const container = useRef<HTMLDivElement | null>(null);
  const instance = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!container.current) return;
    const chartInstance = echarts.init(container.current, undefined, {
      renderer: "canvas",
    });
    instance.current = chartInstance;
    const observer = new ResizeObserver(() => chartInstance.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      chartInstance.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    const th = chartTheme(dark);
    const shorten = (name: string) =>
      name.length > 28 ? `${name.slice(0, 27)}…` : name;
    const names = chart.series.map((s, i) =>
      shorten(
        s.name
          ? (labels?.[s.name] ?? s.name)
          : ([
              labels?.[s.subject ?? ""] ?? s.subject,
              s.period === "comparison" ? t("before") : null,
            ]
              .filter(Boolean)
              .join(" · ") ?? `${i}`),
      ),
    );
    // one legend row above the plot that scrolls when the names do not fit
    const legend = chart.series.length > 1;
    const rose = chart.kind === "rose";
    const colors = chart.series.map(
      (s, i) => colorOf?.(s) ?? PALETTE[i % PALETTE.length],
    );
    const option: echarts.EChartsCoreOption = {
      animation: false,
      color: colors,
      tooltip: {
        trigger: rose ? "item" : "axis",
        backgroundColor: th.tooltipBg,
        textStyle: { color: th.tooltipText, fontSize: 11 },
      },
      legend: legend
        ? {
            type: "scroll",
            top: 0,
            left: 44,
            right: 12,
            textStyle: { color: th.text, fontSize: 11 },
            pageTextStyle: { color: th.text },
          }
        : undefined,
      grid: rose
        ? undefined
        : { left: 44, right: 12, top: legend ? 44 : 24, bottom: 24 },
      ...(rose
        ? {
            polar: { center: ["50%", legend ? "58%" : "52%"], radius: "60%" },
            angleAxis: {
              type: "category",
              data: chart.series[0]?.data.map((d) => String(d[0])) ?? [],
              axisLabel: { color: th.text, fontSize: 10 },
            },
            radiusAxis: {
              axisLabel: { show: false },
              splitLine: { lineStyle: { color: th.grid } },
            },
          }
        : {
            xAxis: {
              type:
                typeof chart.series[0]?.data[0]?.[0] === "number"
                  ? "time"
                  : "category",
              axisLabel: {
                color: th.text,
                fontSize: 10,
                hideOverlap: true,
                // a few long category names (areas) all show, shortened
                ...(typeof chart.series[0]?.data[0]?.[0] === "string" &&
                (chart.series[0]?.data.length ?? 0) <= 8
                  ? { interval: 0, width: 90, overflow: "truncate" as const }
                  : {}),
              },
              axisLine: { lineStyle: { color: th.grid } },
              splitLine: { show: false },
            },
            yAxis: {
              type: "value",
              name: chart.unit ?? undefined,
              nameTextStyle: { color: th.text, fontSize: 10 },
              axisLabel: { color: th.text, fontSize: 10 },
              splitLine: { lineStyle: { color: th.grid } },
            },
          }),
      series: chart.series.map((s, i) => ({
        name: names[i],
        type: chart.kind === "line" ? "line" : "bar",
        coordinateSystem: rose ? "polar" : "cartesian2d",
        stack: chart.kind === "stacked" ? "all" : undefined,
        data: rose ? s.data.map((d) => d[1]) : s.data,
        showSymbol: false,
        connectNulls: true,
        lineStyle: {
          width: 1.5,
          type: s.period === "comparison" ? "dashed" : "solid",
        },
        itemStyle: s.period === "comparison" ? { opacity: 0.55 } : undefined,
        areaStyle:
          chart.kind === "line" && chart.series.length === 1
            ? { opacity: 0.1 }
            : undefined,
      })),
    };
    instance.current?.setOption(option, true);
  }, [chart, labels, colorOf, dark, t]);
  return (
    <div
      ref={container}
      className={className ?? "h-56 w-full"}
      role="img"
      aria-label={labels?.[chart.key] ?? chart.key}
    />
  );
}
