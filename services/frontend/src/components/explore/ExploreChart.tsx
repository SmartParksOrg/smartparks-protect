import { useTranslation } from "react-i18next";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { type ChartType, formatInZone, histogram } from "@/lib/analytics";
import type { ChartGroup } from "@/lib/explore";

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  AxisPointerComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

/** Brand palette first, then muted variants; one colour per owner across every grid. */
const PALETTE = [
  "#52735E",
  "#EDA08F",
  "#7D8FB3",
  "#C6B187",
  "#90AE9B",
  "#B86B5C",
  "#5C7FA3",
  "#8A7A4F",
  "#3E5A48",
  "#D8B4AA",
];
const MARK = "#B86B5C";

/**
 * The chart of the Explore canvas (decisions D152 and D154): one grid per metric with a shared
 * time axis, one series per owner in the owner's colour, or one scatter of a metric against
 * another. Hovering reports the moment under the pointer; a moment marked elsewhere (the
 * drawer, the map) shows here as the axis pointer, and the pinned moment as a line.
 */
export function ExploreChart({
  groups,
  kind,
  xLabel,
  timezone,
  marked,
  pinned,
  onHover,
  onPick,
}: {
  groups: ChartGroup[];
  kind: ChartType;
  /** The x axis label of a scatter chart. */
  xLabel?: string | null;
  timezone: string;
  /** The moment marked from another view, in ms, or null. */
  marked: number | null;
  /** The moment pinned in the URL, in ms, or null. */
  pinned: number | null;
  onHover: (ms: number | null) => void;
  onPick: (ms: number) => void;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const hovering = useRef(false);
  const handlers = useRef({ onHover, onPick, kind });
  useEffect(() => {
    handlers.current = { onHover, onPick, kind };
  }, [onHover, onPick, kind]);

  useEffect(() => {
    if (!container.current) return;
    const instance = echarts.init(container.current, undefined, {
      renderer: "canvas",
    });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(container.current);
    const zr = instance.getZr();
    // the moment under the pointer on a time axis: the pixel converted through the first grid
    const momentAt = (event: { offsetX: number; offsetY: number }) => {
      if (!isTimeAxis(handlers.current.kind)) return null;
      const point = instance.convertFromPixel({ gridIndex: 0 }, [
        event.offsetX,
        event.offsetY,
      ]) as unknown;
      const ms = Array.isArray(point) ? point[0] : null;
      return typeof ms === "number" && Number.isFinite(ms) ? ms : null;
    };
    zr.on("mousemove", (event: { offsetX: number; offsetY: number }) => {
      hovering.current = true;
      const ms = momentAt(event);
      if (ms !== null) handlers.current.onHover(ms);
    });
    zr.on("click", (event: { offsetX: number; offsetY: number }) => {
      const ms = momentAt(event);
      if (ms !== null) handlers.current.onPick(ms);
    });
    zr.on("globalout", () => {
      hovering.current = false;
      handlers.current.onHover(null);
    });
    // a scatter point carries its moment third
    instance.on("mouseover", (event: unknown) => {
      const data = (event as { data?: unknown }).data;
      if (
        Array.isArray(data) &&
        data.length === 3 &&
        typeof data[2] === "number"
      )
        handlers.current.onHover(data[2]);
    });
    instance.on("click", (event: unknown) => {
      const data = (event as { data?: unknown }).data;
      if (!Array.isArray(data)) return;
      const ms = data.length === 3 ? data[2] : data[0];
      if (typeof ms === "number") handlers.current.onPick(ms);
    });
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    instance.setOption(
      buildOption(groups, kind, xLabel ?? null, timezone, pinned),
      true,
    );
  }, [groups, kind, xLabel, timezone, pinned]);

  useEffect(() => {
    const instance = chart.current;
    if (!instance || hovering.current || !isTimeAxis(kind)) return;
    if (marked === null || groups.length === 0) {
      instance.dispatchAction({ type: "hideTip" });
      return;
    }
    const x = instance.convertToPixel({ xAxisIndex: 0 }, marked);
    if (typeof x !== "number" || !Number.isFinite(x)) return;
    const top = (instance.getHeight() * gridTop(0, groups.length)) / 100 + 4;
    instance.dispatchAction({ type: "showTip", x, y: top });
  }, [marked, groups, kind]);

  return (
    <div
      ref={container}
      className="absolute inset-0"
      role="img"
      aria-label={t("Chart of the selection")}
    />
  );
}

function isTimeAxis(kind: ChartType): boolean {
  return kind === "line" || kind === "bar" || kind === "state";
}

const LEGEND_PCT = 7;
const FOOT_PCT = 10;

function gridTop(index: number, count: number): number {
  return LEGEND_PCT + (index * (100 - LEGEND_PCT - FOOT_PCT)) / count;
}

function gridHeight(count: number): number {
  return (100 - LEGEND_PCT - FOOT_PCT) / count - 5;
}

function owners(groups: ChartGroup[]): Map<string, number> {
  const index = new Map<string, number>();
  for (const g of groups)
    for (const s of g.series)
      if (!index.has(s.ownerId)) index.set(s.ownerId, index.size);
  return index;
}

function valueText(value: unknown, unit: string | null): string {
  if (typeof value !== "number") return String(value ?? "");
  return `${Number.isInteger(value) ? value : value.toFixed(3)}${unit ? ` ${unit}` : ""}`;
}

function buildOption(
  groups: ChartGroup[],
  kind: ChartType,
  xLabel: string | null,
  timezone: string,
  pinned: number | null,
): echarts.EChartsCoreOption {
  const colours = owners(groups);
  const colourOf = (ownerId: string) =>
    PALETTE[(colours.get(ownerId) ?? 0) % PALETTE.length];
  const base: echarts.EChartsCoreOption = {
    color: PALETTE,
    animation: false,
    legend: { type: "scroll", top: 4, textStyle: { fontSize: 11 } },
  };
  if (groups.length === 0) return { ...base, legend: { show: false } };
  const timeLabel = (value: number) =>
    formatInZone(new Date(value).toISOString(), timezone, {
      dateStyle: undefined,
      timeStyle: undefined,
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  if (kind === "scatter") {
    const group = groups[0];
    return {
      ...base,
      grid: { left: 64, right: 24, top: 40, bottom: 48 },
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const p = params as { seriesName: string; data: number[] };
          return `${p.seriesName}<br/>${xLabel ?? "x"}: ${valueText(p.data[0], null)}<br/>${group.label}: ${valueText(p.data[1], group.unit)}<br/>${timeLabel(p.data[2])}`;
        },
      },
      xAxis: { type: "value", name: xLabel ?? undefined, scale: true },
      yAxis: {
        type: "value",
        name: group.unit ? `${group.label} (${group.unit})` : group.label,
        scale: true,
      },
      dataZoom: [{ type: "inside" }],
      series: group.series.map((s) => ({
        type: "scatter",
        name: s.name,
        data: s.data,
        symbolSize: 5,
        itemStyle: { color: colourOf(s.ownerId) },
      })),
    };
  }

  const count = groups.length;
  const grids = groups.map((_, i) => ({
    left: 64,
    right: 24,
    top: `${gridTop(i, count)}%`,
    height: `${gridHeight(count)}%`,
  }));

  if (kind === "histogram") {
    const series: unknown[] = [];
    const xAxis: unknown[] = [];
    const yAxis: unknown[] = [];
    groups.forEach((g, i) => {
      const values = g.series.flatMap((s) => s.data.map((d) => d[1]));
      const { edges, counts } = histogram(values);
      xAxis.push({
        type: "category",
        gridIndex: i,
        data: edges.map((e) =>
          Number.isInteger(e) ? String(e) : e.toFixed(2),
        ),
        name: g.unit ?? undefined,
      });
      yAxis.push({ type: "value", gridIndex: i, name: g.label });
      series.push({
        type: "bar",
        name: g.label,
        xAxisIndex: i,
        yAxisIndex: i,
        data: counts,
        itemStyle: { color: PALETTE[i % PALETTE.length] },
      });
    });
    return {
      ...base,
      legend: { show: false },
      tooltip: { trigger: "item" },
      grid: grids,
      xAxis,
      yAxis,
      series,
    };
  }

  const xAxis = groups.map((_, i) => ({
    type: "time",
    gridIndex: i,
    axisLabel: { formatter: timeLabel, show: i === count - 1 },
    axisPointer: { label: { show: i === count - 1 } },
  }));
  const yAxis = groups.map((g, i) => ({
    type: "value",
    gridIndex: i,
    name: g.unit ? `${g.label} (${g.unit})` : g.label,
    nameTextStyle: { align: "left", fontSize: 11 },
    scale: kind !== "bar",
  }));
  const series = groups.flatMap((g, i) =>
    g.series.map((s, j) => {
      const common = {
        name: s.name,
        xAxisIndex: i,
        yAxisIndex: i,
        data: s.data,
        itemStyle: { color: colourOf(s.ownerId) },
        lineStyle: { color: colourOf(s.ownerId) },
        markLine:
          pinned !== null && j === 0
            ? {
                silent: true,
                symbol: "none",
                lineStyle: { color: MARK, width: 1.5 },
                label: { show: false },
                data: [{ xAxis: pinned }],
              }
            : undefined,
      };
      if (kind === "state")
        return {
          ...common,
          type: "line",
          step: "end",
          showSymbol: false,
          areaStyle: { opacity: 0.12 },
        };
      if (kind === "bar") return { ...common, type: "bar", barMaxWidth: 12 };
      return {
        ...common,
        type: "line",
        showSymbol: s.data.length < 200,
        connectNulls: false,
      };
    }),
  );
  return {
    ...base,
    tooltip: {
      trigger: "axis",
      valueFormatter: (v: unknown) => valueText(v, null),
    },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      label: { backgroundColor: "#52735E" },
    },
    grid: grids,
    xAxis,
    yAxis,
    dataZoom: [
      { type: "inside", xAxisIndex: groups.map((_, i) => i) },
      {
        type: "slider",
        xAxisIndex: groups.map((_, i) => i),
        height: 16,
        bottom: 6,
      },
    ],
    series,
  };
}
