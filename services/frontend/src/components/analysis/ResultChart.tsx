import { useTranslation } from "react-i18next";
import { BarChart, GraphChart, LineChart } from "echarts/charts";
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
  GraphChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  PolarComponent,
  CanvasRenderer,
]);

/** A chart of a result document: a line or bar over time, a stacked bar, a rose of directions,
 * or the contact network; the data comes from the document, the look from the brand palette. */
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
    if (chart.kind === "network") {
      instance.current?.setOption(networkOption(chart, th, dark, t), true);
      return;
    }
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
              data: chart.series[0]?.data?.map((d) => String(d[0])) ?? [],
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
                typeof chart.series[0]?.data?.[0]?.[0] === "number"
                  ? "time"
                  : "category",
              axisLabel: {
                color: th.text,
                fontSize: 10,
                hideOverlap: true,
                // a few long category names (areas) all show, shortened
                ...(typeof chart.series[0]?.data?.[0]?.[0] === "string" &&
                (chart.series[0]?.data?.length ?? 0) <= 8
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
        data: rose ? (s.data ?? []).map((d) => d[1]) : (s.data ?? []),
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
      className={
        className ?? (chart.kind === "network" ? "h-80 w-full" : "h-56 w-full")
      }
      role="img"
      aria-label={labels?.[chart.key] ?? chart.key}
    />
  );
}

/** The contact network: subjects as nodes, pairs that met as edges (design section 4.3).
 *
 * The one picture that makes a contact study legible. A node is sized by how many contacts the
 * subject had, so the animals at the centre of the network are the ones that stand out; an edge
 * is thicker the more the pair met, and dashed when only one kind of evidence saw them, because
 * a pair both kinds found is a different claim from one only the fixes support.
 *
 * A subject that met nobody stays on the picture as a small unattached dot. Leaving it out would
 * answer a different question: "who met" rather than "who met whom", and the animals that met
 * nothing at all are often the finding.
 */
function networkOption(
  chart: ResultChartData,
  th: ReturnType<typeof chartTheme>,
  dark: boolean,
  t: (key: string, options?: Record<string, unknown>) => string,
): echarts.EChartsCoreOption {
  const series = chart.series[0];
  const nodes = series?.nodes ?? [];
  const edges = series?.edges ?? [];
  const busiest = Math.max(1, ...nodes.map((n) => n.contacts));
  const heaviest = Math.max(1, ...edges.map((e) => e.contacts));
  // A force layout reads well while it fits: it groups the animals that met each other, which
  // is the thing worth seeing. It does not fit for long — nothing bounds it to the box, so a
  // study of forty subjects pushes most of them off the canvas and shows nine. Past a dozen the
  // circle wins, as it does in the PDF: every subject is visible and in the same place each
  // time, and with many subjects the edges carry the structure anyway.
  const crowded = nodes.length > 12;
  return {
    animation: false,
    tooltip: {
      backgroundColor: th.tooltipBg,
      textStyle: { color: th.tooltipText, fontSize: 11 },
      formatter: (params: {
        dataType?: string;
        data?: Record<string, unknown>;
      }) => {
        const data = params.data ?? {};
        if (params.dataType === "edge") {
          return t("{{contacts}} contacts · {{hours}} h · {{evidence}}", {
            contacts: data.contacts,
            hours: data.hours,
            evidence: data.evidence,
          });
        }
        return t("{{name}}: {{contacts}} contacts", {
          name: data.name,
          contacts: data.contacts,
        });
      },
    },
    series: [
      {
        type: "graph",
        layout: crowded ? "circular" : "force",
        circular: { rotateLabel: false },
        roam: true,
        draggable: !crowded,
        force: { repulsion: 220, edgeLength: [40, 120], gravity: 0.08 },
        label: {
          show: true,
          position: "right",
          color: th.text,
          fontSize: 10,
          formatter: (p: { data?: { name?: string } }) => p.data?.name ?? "",
        },
        emphasis: { focus: "adjacency" },
        data: nodes.map((n) => ({
          id: n.id,
          name: n.name,
          contacts: n.contacts,
          symbolSize: 8 + 22 * Math.sqrt(n.contacts / busiest),
          itemStyle: {
            color: n.contacts ? PALETTE[0] : dark ? "#4b5563" : "#cbd5e1",
            borderColor: dark ? "#0b1220" : "#ffffff",
            borderWidth: 1,
          },
        })),
        links: edges.map((e) => ({
          source: e.source,
          target: e.target,
          contacts: e.contacts,
          hours: e.hours,
          evidence: e.evidence,
          lineStyle: {
            width: 1 + 4 * (e.contacts / heaviest),
            // an edge carries data, so it is drawn darker than a gridline and fades with its
            // own weight rather than with the grid; at the gridline colour a thin dashed line
            // is invisible and the pairs it stands for are the finding
            opacity: 0.45 + 0.45 * (e.contacts / heaviest),
            color: dark ? "#6b7f75" : "#9AA8A0",
            // one kind of evidence is a weaker claim than two, and the line says so
            type: e.evidence.includes("+") ? "solid" : "dashed",
          },
        })),
      },
    ],
  };
}
