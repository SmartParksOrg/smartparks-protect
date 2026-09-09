import { useTranslation } from "react-i18next";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";

import { type ChartType, formatInZone, histogram } from "@/lib/analytics";
import { axisIndexOf, type ChartGroup, unitAxes } from "@/lib/explore";
import {
  type ChartLine,
  chartLines,
  GRID,
  MARK,
  PALETTE,
  TEXT,
} from "@/lib/chartStyle";

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AxisPointerComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

/**
 * The chart of the Explore canvas (decisions D152 and D154): one graph, one thin line per
 * metric and owner over a shared time axis, the axes decided by unit (the first unit left,
 * the others right), markers only under the pointer, one crosshair and one value card, and
 * legend chips above that toggle lines. Hovering reports the moment under the pointer; a
 * moment marked elsewhere (the drawer, the map) shows here as the crosshair, and the pinned
 * moment as a thin dashed line.
 */
export function ExploreChart({
  groups,
  kind,
  xLabel,
  timezone,
  phone = false,
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
  /** No zoom strip on a phone: pinch and drag zoom the chart. */
  phone?: boolean;
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
  const [hidden, setHidden] = useState<string[]>([]);
  const lines = useMemo(() => chartLines(groups), [groups]);
  const shown = useMemo(
    () => lines.filter((l) => !hidden.includes(l.key)),
    [lines, hidden],
  );

  useEffect(() => {
    if (!container.current) return;
    const instance = echarts.init(container.current, undefined, {
      renderer: "canvas",
    });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(container.current);
    const zr = instance.getZr();
    // the moment under the pointer on a time axis: the pixel converted through the grid
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
      if (
        Array.isArray(data) &&
        data.length === 3 &&
        typeof data[2] === "number"
      )
        handlers.current.onPick(data[2]);
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
      buildOption(shown, groups, kind, xLabel ?? null, timezone, phone, pinned),
      true,
    );
  }, [shown, groups, kind, xLabel, timezone, phone, pinned]);

  useEffect(() => {
    const instance = chart.current;
    if (!instance || hovering.current || !isTimeAxis(kind)) return;
    if (marked === null || shown.length === 0) {
      instance.dispatchAction({ type: "hideTip" });
      return;
    }
    const x = instance.convertToPixel({ xAxisIndex: 0 }, marked);
    if (typeof x !== "number" || !Number.isFinite(x)) return;
    instance.dispatchAction({ type: "showTip", x, y: 40 });
  }, [marked, shown, kind]);

  return (
    <div className="absolute inset-0 flex flex-col">
      {kind !== "histogram" && lines.length > 0 && (
        <div className="flex shrink-0 gap-1.5 overflow-x-auto px-3 pt-2 pb-1 [scrollbar-width:none]">
          {lines.map((line) => {
            const off = hidden.includes(line.key);
            return (
              <button
                key={line.key}
                type="button"
                aria-pressed={!off}
                className={`flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs whitespace-nowrap ${off ? "text-muted-foreground opacity-60" : "bg-card"}`}
                onClick={() =>
                  setHidden((h) =>
                    off ? h.filter((k) => k !== line.key) : [...h, line.key],
                  )
                }
              >
                <span
                  className="inline-block size-2 rounded-full"
                  style={{
                    background: off ? "transparent" : line.colour,
                    boxShadow: `inset 0 0 0 1.5px ${line.colour}`,
                  }}
                />
                {line.name}
                {line.group.unit && (
                  <span className="text-muted-foreground">
                    {line.group.unit}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
      <div
        ref={container}
        className="min-h-0 flex-1"
        role="img"
        aria-label={t("Chart of the selection")}
      />
    </div>
  );
}

function isTimeAxis(kind: ChartType): boolean {
  return kind === "line" || kind === "bar" || kind === "state";
}

function valueText(value: unknown, unit: string | null): string {
  if (typeof value !== "number") return String(value ?? "");
  const text = Number.isInteger(value)
    ? String(value)
    : Math.abs(value) >= 100
      ? value.toFixed(1)
      : value.toFixed(2);
  return `${text}${unit ? ` ${unit}` : ""}`;
}

const AXIS_TEXT = { color: TEXT, fontSize: 11 };

function timeFormatter(span: number, timezone: string) {
  const day = 24 * 3600_000;
  return (value: number) => {
    const iso = new Date(value).toISOString();
    if (span >= 3 * day)
      return formatInZone(iso, timezone, {
        dateStyle: undefined,
        timeStyle: undefined,
        day: "numeric",
        month: "short",
      });
    if (span >= day)
      return formatInZone(iso, timezone, {
        dateStyle: undefined,
        timeStyle: undefined,
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    return formatInZone(iso, timezone, {
      dateStyle: undefined,
      timeStyle: undefined,
      hour: "2-digit",
      minute: "2-digit",
    });
  };
}

function card(
  title: string,
  rows: { colour: string; name: string; value: string }[],
): string {
  const lines = rows
    .map(
      (r) =>
        `<div style="display:flex;align-items:center;gap:8px;margin-top:2px"><span style="width:8px;height:8px;border-radius:9999px;background:${r.colour};flex:none"></span><span style="color:${TEXT};flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis">${r.name}</span><b style="font-variant-numeric:tabular-nums">${r.value}</b></div>`,
    )
    .join("");
  return `<div style="font-size:12px;min-width:160px"><div style="color:${TEXT};margin-bottom:4px">${title}</div>${lines}</div>`;
}

function buildOption(
  lines: ChartLine[],
  groups: ChartGroup[],
  kind: ChartType,
  xLabel: string | null,
  timezone: string,
  phone: boolean,
  pinned: number | null,
): echarts.EChartsCoreOption {
  const base: echarts.EChartsCoreOption = {
    animation: false,
    textStyle: { fontFamily: "inherit" },
    tooltip: {
      backgroundColor: "rgba(255,255,255,0.96)",
      borderColor: GRID,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: "#111827", fontSize: 12 },
      extraCssText:
        "box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-radius: 8px;",
      confine: true,
    },
  };
  if (lines.length === 0) return base;
  const span =
    Math.max(...lines.flatMap((l) => l.data.map((d) => d[0]))) -
    Math.min(...lines.flatMap((l) => l.data.map((d) => d[0])));
  const timeLabel = timeFormatter(span, timezone);
  const timeTitle = (value: number) =>
    formatInZone(new Date(value).toISOString(), timezone, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  const grid = {
    left: 48,
    right: 16,
    top: 24,
    bottom: phone ? 28 : 56,
    containLabel: false,
  };
  // a value axis that hugs the data (Tim, 2026-09-09: the detail matters, a battery between
  // 4.09 and 4.12 V fills the graph), with a little air, rounded to a clean step; a constant
  // series gets a sliver of range so it still draws as a line
  const bounds = (extent: { min: number; max: number }): [number, number] => {
    const spread = extent.max - extent.min;
    const pad =
      spread > 0
        ? spread * 0.08
        : Math.abs(extent.max || extent.min || 1) * 0.005;
    // ECharts splits the axis into about five nice steps (1, 2, 3, 5 or 10 times a power of
    // ten); the bounds settle on multiples of that step, so no edge label sits off the grid
    const nice = (v: number) => {
      const e = 10 ** Math.floor(Math.log10(v));
      const f = v / e;
      return e * (f < 1.5 ? 1 : f < 2.5 ? 2 : f < 4 ? 3 : f < 7 ? 5 : 10);
    };
    const tidy = (v: number) => Number(v.toFixed(10));
    let low = extent.min - pad;
    let high = extent.max + pad;
    for (let i = 0; i < 4; i++) {
      const step = nice((high - low) / 5);
      const nextLow = tidy(Math.floor(low / step) * step);
      const nextHigh = tidy(Math.ceil(high / step) * step);
      if (nextLow === low && nextHigh === high) break;
      low = nextLow;
      high = nextHigh;
    }
    return [low, high];
  };
  const valueAxis = {
    type: "value",
    scale: true,
    min: (extent: { min: number; max: number }) => bounds(extent)[0],
    max: (extent: { min: number; max: number }) => bounds(extent)[1],
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: AXIS_TEXT,
    splitLine: { lineStyle: { color: GRID } },
    nameTextStyle: { ...AXIS_TEXT, align: "left" },
    nameGap: 8,
  };

  if (kind === "scatter") {
    const group = groups[0];
    return {
      ...base,
      tooltip: {
        ...(base.tooltip as object),
        trigger: "item",
        formatter: (params: unknown) => {
          const p = params as {
            seriesName: string;
            data: number[];
            color: string;
          };
          return card(timeTitle(p.data[2]), [
            {
              colour: p.color,
              name: xLabel ?? "x",
              value: valueText(p.data[0], null),
            },
            {
              colour: p.color,
              name: p.seriesName,
              value: valueText(p.data[1], group.unit),
            },
          ]);
        },
      },
      grid: { ...grid, bottom: 40 },
      xAxis: {
        ...valueAxis,
        name: xLabel ?? undefined,
        nameLocation: "middle",
        nameGap: 26,
        splitLine: { show: false },
      },
      yAxis: { ...valueAxis, name: group.unit ?? undefined },
      dataZoom: [{ type: "inside" }],
      series: lines.map((l) => ({
        type: "scatter",
        name: l.name,
        data: l.data,
        symbolSize: 6,
        itemStyle: { color: l.colour, opacity: 0.85 },
      })),
    };
  }

  if (kind === "histogram") {
    // the distribution of the first metric; the others would need their own bins
    const group = groups[0];
    const values = group.series.flatMap((s) => s.data.map((d) => d[1]));
    const { edges, counts } = histogram(values);
    return {
      ...base,
      tooltip: { ...(base.tooltip as object), trigger: "item" },
      grid: { ...grid, bottom: 40 },
      xAxis: {
        type: "category",
        data: edges.map((e) =>
          Number.isInteger(e) ? String(e) : e.toFixed(2),
        ),
        name: group.unit ? `${group.label} (${group.unit})` : group.label,
        nameLocation: "middle",
        nameGap: 26,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: AXIS_TEXT,
      },
      yAxis: { ...valueAxis, min: 0, max: undefined, name: "count" },
      series: [
        {
          type: "bar",
          name: group.label,
          data: counts,
          itemStyle: { color: PALETTE[0] },
        },
      ],
    };
  }

  const units = unitAxes(groups);
  const yAxis: unknown[] = [{ ...valueAxis, name: units[0] ?? "" }];
  if (units.length > 1)
    yAxis.push({
      ...valueAxis,
      name: units.slice(1).join(" / "),
      nameTextStyle: { ...AXIS_TEXT, align: "right" },
      position: "right",
      splitLine: { show: false },
    });
  const series = lines.map((l, i) => {
    const common = {
      name: l.name,
      yAxisIndex: yAxis.length > 1 ? axisIndexOf(l.group, units) : 0,
      data: l.data,
      itemStyle: { color: l.colour },
      lineStyle: { color: l.colour, width: 1.5 },
      emphasis: { focus: "none", lineStyle: { width: 2 } },
      markLine:
        pinned !== null && i === 0
          ? {
              silent: true,
              symbol: "none",
              lineStyle: {
                color: MARK,
                width: 1,
                type: "dashed",
                opacity: 0.8,
              },
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
        areaStyle: { opacity: 0.1 },
      };
    if (kind === "bar") return { ...common, type: "bar", barMaxWidth: 10 };
    // small filled points on every moment, a little larger under the pointer; a very dense
    // line would turn into a band, so above a thousand points they appear on hover only
    return {
      ...common,
      type: "line",
      showSymbol: l.data.length <= 1000,
      symbol: "circle",
      symbolSize: 4,
      emphasis: { focus: "none", scale: 1.6, lineStyle: { width: 2 } },
      connectNulls: false,
    };
  });
  return {
    ...base,
    tooltip: {
      ...(base.tooltip as object),
      trigger: "axis",
      axisPointer: {
        type: "line",
        snap: true,
        lineStyle: { color: TEXT, width: 1 },
      },
      formatter: (params: unknown) => {
        const items = params as {
          seriesName: string;
          seriesIndex: number;
          color: string;
          value: number[];
        }[];
        if (!items.length) return "";
        return card(
          timeTitle(items[0].value[0]),
          items.map((p) => ({
            colour: p.color,
            name: p.seriesName,
            value: valueText(
              p.value[1],
              lines[p.seriesIndex]?.group.unit ?? null,
            ),
          })),
        );
      },
    },
    grid,
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: GRID } },
      axisTick: { show: false },
      axisLabel: { ...AXIS_TEXT, formatter: timeLabel, hideOverlap: true },
      splitLine: { show: false },
      axisPointer: { label: { show: false } },
    },
    yAxis,
    dataZoom: phone
      ? [{ type: "inside" }]
      : [
          { type: "inside" },
          {
            type: "slider",
            height: 18,
            bottom: 8,
            borderColor: GRID,
            fillerColor: "rgba(82,115,94,0.12)",
            dataBackground: {
              lineStyle: { color: GRID },
              areaStyle: { color: "#F3F4F6" },
            },
            selectedDataBackground: {
              lineStyle: { color: "#52735E" },
              areaStyle: { color: "rgba(82,115,94,0.15)" },
            },
            handleStyle: { borderColor: GRID },
            textStyle: AXIS_TEXT,
          },
        ],
    series,
  };
}
