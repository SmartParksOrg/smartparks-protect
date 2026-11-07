import { useTranslation } from "react-i18next";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import type { GatewayDay } from "@/api/types";
import { useTheme } from "@/hooks/useTheme";
import { PALETTE, chartMotion, chartTheme } from "@/lib/chartStyle";
import { useReducedMotion } from "@/lib/motion";

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

/** Every UTC day of the window, so a day the gateway relayed nothing shows as a gap. */
function daysOf(hours: number): string[] {
  const out: string[] = [];
  const end = new Date();
  end.setUTCHours(0, 0, 0, 0);
  const count = Math.max(1, Math.ceil(hours / 24));
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(end.getTime() - i * 86_400_000);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

/**
 * The receptions a gateway relayed per day over the window (decision D369), as bars: the
 * gateway page's Traffic tab reads the days before the messages, so a gateway that fell
 * silent shows the day it stopped.
 */
export function GatewayDaysChart({ days, hours }: { days: GatewayDay[]; hours: number }) {
  const { t } = useTranslation();
  const { resolved } = useTheme();
  const reduced = useReducedMotion();
  const element = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!element.current) return;
    const instance = echarts.init(element.current, undefined, { renderer: "canvas" });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    const theme = chartTheme(resolved === "dark");
    const axis = daysOf(hours);
    const byDay = new Map(days.map((d) => [d.day, d]));
    instance.setOption(
      {
        ...chartMotion(reduced),
        grid: { left: 44, right: 12, top: 12, bottom: 28 },
        tooltip: {
          trigger: "axis",
          formatter: (params: unknown) => {
            const items = params as { axisValue: string; data: number }[];
            const day = byDay.get(items[0]?.axisValue ?? "");
            if (!day) return `${items[0]?.axisValue ?? ""}: ${t("no receptions")}`;
            return [
              day.day,
              t("{{count}} receptions", { count: day.receptions }),
              t("{{count}} devices", { count: day.devices }),
              day.mean_rssi != null ? `${day.mean_rssi} dBm` : "",
            ]
              .filter(Boolean)
              .join("<br>");
          },
        },
        xAxis: {
          type: "category",
          data: axis,
          axisLabel: { color: theme.text, fontSize: 10, formatter: (v: string) => v.slice(5) },
          axisLine: { lineStyle: { color: theme.grid } },
          axisTick: { show: false },
        },
        yAxis: {
          type: "value",
          minInterval: 1,
          axisLabel: { color: theme.text, fontSize: 10 },
          splitLine: { lineStyle: { color: theme.grid } },
        },
        series: [
          {
            type: "bar",
            data: axis.map((day) => byDay.get(day)?.receptions ?? 0),
            itemStyle: { color: PALETTE[0], borderRadius: [2, 2, 0, 0] },
            barMaxWidth: 24,
          },
        ],
      },
      true,
    );
  }, [days, hours, resolved, reduced, t]);
  return (
    <div
      ref={element}
      className="h-48 w-full"
      role="img"
      aria-label={t("Receptions per day over the window")}
    />
  );
}
