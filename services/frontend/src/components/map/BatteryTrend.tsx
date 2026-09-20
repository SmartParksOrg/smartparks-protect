import { useTranslation } from "react-i18next";

import { batteryTypeLabel } from "@/lib/battery";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { SeriesResponse } from "@/api/types";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";

import { useNow } from "@/hooks/useNow";
import { useTheme } from "@/hooks/useTheme";
import { chartTheme } from "@/lib/chartStyle";
import { formatInZone } from "@/lib/analytics";
import { browserTimezone, type RangePreset, rangeFor } from "@/lib/analytics";
import { formatAgo, formatDuration, formatTime } from "@/lib/format";
import { stillHours } from "@/lib/movement";
import { decimalsFor, niceStep, type TrendSpec } from "@/lib/trend";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const RANGES: RangePreset[] = ["24h", "7d", "30d"];
const RANGE_LABELS: Record<string, string> = {
  "24h": "24 h",
  "7d": "7 d",
  "30d": "30 d",
};

/** The battery value of an entity or device panel as a button that unfolds the recent trend
 * inside the panel (Tim, 2026-09-14): a small line of the device's battery voltage over the
 * last day, week or month from the analytics series, so a person sees whether it drops
 * without leaving the map or covering it. The movement value below works the same way. */
export function BatteryValue({
  deviceId,
  voltage,
  percent,
  batteryType,
  open,
  onToggle,
  className,
}: {
  deviceId: string | null | undefined;
  voltage: number;
  /** The share of charge the device's battery type makes of the voltage (decision D248). */
  percent?: number | null;
  /** Which chemistry judged it, for the explanation behind the value. */
  batteryType?: string | null;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const label =
    percent != null
      ? `${voltage.toFixed(2)} V · ${percent}%`
      : `${voltage.toFixed(2)} V`;
  // a voltage says nothing without the chemistry it is read against (Tim, 2026-09-18)
  const explain = batteryType
    ? t("{{percent}}% left, read as {{type}}", {
        percent: percent ?? 0,
        type: batteryTypeLabel(batteryType, t),
      })
    : t(
        "No battery type known for this device, so the voltage is judged by the driver.",
      );
  if (!deviceId)
    return (
      <span className={className} title={explain}>
        {label}
      </span>
    );
  return (
    <button
      type="button"
      className={`underline underline-offset-2 hover:text-primary ${className ?? ""}`}
      title={`${explain} ${open ? t("Hide the battery trend") : t("Show the battery trend")}`}
      aria-expanded={open}
      onClick={onToggle}
    >
      {label}
    </button>
  );
}

/** The battery trend: mounted while unfolded, so the series is read on demand. */
export function BatteryTrend({
  projectId,
  deviceId,
  until,
}: {
  projectId: string;
  deviceId: string;
  until?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <MetricTrend
      projectId={projectId}
      deviceId={deviceId}
      until={until}
      spec={{
        metric: "battery_voltage",
        label: t("Battery"),
        unit: "V",
        decimals: 2,
        step: 0.05,
        ariaLabel: t("Battery voltage over the period"),
      }}
    />
  );
}

/** The movement value of a panel: moving, or still for so long, as the button that unfolds
 * the movement trend (Tim, 2026-09-14), the same way as the battery. */
export function MovementValue({
  deviceId,
  lastMovementAt,
  now,
  open,
  onToggle,
  className,
}: {
  deviceId: string | null | undefined;
  lastMovementAt: string | null | undefined;
  now: number;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const still = stillHours(lastMovementAt, now);
  const label = !lastMovementAt
    ? t("no movement seen yet")
    : still === null
      ? t("moving, {{ago}}", { ago: formatAgo(lastMovementAt, now) })
      : still >= 48
        ? t("still for {{days}} d", { days: Math.floor(still / 24) })
        : t("still for {{hours}} h", { hours: still });
  if (!deviceId) return <span className={className}>{label}</span>;
  return (
    <button
      type="button"
      className={`underline underline-offset-2 hover:text-primary ${className ?? ""}`}
      title={open ? t("Hide the movement trend") : t("Show the movement trend")}
      aria-expanded={open}
      onClick={onToggle}
    >
      {label}
    </button>
  );
}

/** The movement trend: the change of the accelerometer between status messages, flat at
 * zero while the device lies still. */
export function MovementTrend({
  projectId,
  deviceId,
  until,
}: {
  projectId: string;
  deviceId: string;
  until?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <MetricTrend
      projectId={projectId}
      deviceId={deviceId}
      until={until}
      spec={{
        metric: "activity",
        label: t("Movement"),
        unit: "m/s²",
        decimals: 1,
        step: 0.5,
        floor: 0,
        ariaLabel: t("Movement over the period"),
      }}
    />
  );
}

/** The uptime of a panel as the button that unfolds its trend; a reboot in the last day
 * is said next to it (Tim, 2026-09-14). */
export function UptimeValue({
  deviceId,
  uptimeSeconds,
  lastResetAt,
  now,
  open,
  onToggle,
  className,
}: {
  deviceId: string | null | undefined;
  uptimeSeconds: number;
  lastResetAt: string | null | undefined;
  now: number;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const recent = lastResetAt && now - Date.parse(lastResetAt) < 24 * 3_600_000;
  const label = recent
    ? t("{{uptime}}, rebooted {{ago}}", {
        uptime: formatDuration(uptimeSeconds),
        ago: formatAgo(lastResetAt, now),
      })
    : formatDuration(uptimeSeconds);
  if (!deviceId) return <span className={className}>{label}</span>;
  return (
    <button
      type="button"
      className={`underline underline-offset-2 hover:text-primary ${className ?? ""}`}
      title={open ? t("Hide the uptime trend") : t("Show the uptime trend")}
      aria-expanded={open}
      onClick={onToggle}
    >
      {label}
    </button>
  );
}

/** The uptime trend in days: a drop to zero is a reboot. */
export function UptimeTrend({
  projectId,
  deviceId,
  until,
}: {
  projectId: string;
  deviceId: string;
  until?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <MetricTrend
      projectId={projectId}
      deviceId={deviceId}
      until={until}
      spec={{
        metric: "uptime",
        label: t("Uptime"),
        unit: "d",
        decimals: 1,
        step: 1,
        floor: 0,
        scale: 1 / 86_400,
        ariaLabel: t("Uptime over the period"),
      }}
    />
  );
}

/** How much a scanner hears, over the period (Tim, 2026-09-18).
 *
 * One sample per scan window, and a scan that saw nothing is a zero, so the line falling to the
 * floor means the reader looked and the tags were out of range. A gap in the line means
 * something else entirely: the reader was not looking, or said nothing at all. */
export function ContactsTrend({
  projectId,
  deviceId,
  until,
}: {
  projectId: string;
  deviceId: string;
  until?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <MetricTrend
      projectId={projectId}
      deviceId={deviceId}
      until={until}
      spec={{
        metric: "ble_contacts",
        label: t("Bluetooth contacts"),
        unit: "",
        decimals: 0,
        floor: 0,
        ariaLabel: t("Devices seen per scan over the period"),
      }}
    />
  );
}

/** One metric of a device over the last day, week or month from the analytics series: the
 * battery, movement and uptime trends above, and any numeric metric of the registry from the
 * status panels (Tim, 2026-09-15, `trendSpecFor`). */
export function MetricTrend({
  projectId,
  deviceId,
  spec,
  until,
}: {
  projectId: string;
  deviceId: string;
  spec: TrendSpec;
  /** The device's last record: the period ends there rather than now, so a device silent for
   * a year still shows its last week (Tim, 2026-09-15, decision D207). */
  until?: string | null;
}) {
  const { t } = useTranslation();
  const [range, setRange] = useState<RangePreset>("7d");
  const now = useNow();
  const anchor = trendAnchor(until, now);
  const window = rangeFor(range, anchor);
  const timezone = browserTimezone();
  const series = useQuery({
    queryKey: queryKeys.analyticsSeries(projectId, {
      metric: spec.metric,
      deviceId,
      ...window,
    }),
    queryFn: () =>
      api.get<SeriesResponse>(
        `/api/v1/projects/${projectId}/analytics/series`,
        {
          query: {
            metric: spec.metric,
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
  const scale = spec.scale ?? 1;
  const points = (series.data?.series?.[0]?.points ?? []).map((p) => ({
    time: p.time,
    value: p.values.mean == null ? null : p.values.mean * scale,
  }));
  const values = points
    .map((p) => p.value)
    .filter((v): v is number => v != null);
  const decimals =
    spec.decimals ??
    decimalsFor(
      spec.step ??
        niceStep(Math.min(...values, Infinity), Math.max(...values, -Infinity)),
    );
  const show = (v: number) =>
    spec.words?.[Math.round(v)] !== undefined && Number.isInteger(v)
      ? spec.words[Math.round(v)]
      : `${v.toFixed(decimals)} ${spec.unit}`;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">
          {spec.label}
          {anchor.getTime() < now - 86_400_000 && (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {t("up to {{date}}", { date: formatTime(anchor.toISOString()) })}
            </span>
          )}
        </span>
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
              (p) => [Date.parse(p.time), p.value] as [number, number | null],
            )}
            timezone={timezone}
            spec={spec}
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>
              {t("Low {{value}}", { value: show(Math.min(...values)) })}
            </span>
            <span>
              {t("High {{value}}", { value: show(Math.max(...values)) })}
            </span>
            <span>
              {t("Now {{value}}", { value: show(values[values.length - 1]) })}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

/** Where a trend's period ends: a minute past the device's last record, capped at now. */
function trendAnchor(until: string | null | undefined, now: number): Date {
  const parsed = until ? Date.parse(until) : Number.NaN;
  return new Date(
    Number.isFinite(parsed) ? Math.min(parsed + 60_000, now) : now,
  );
}

/** A small line of one series (decision-free: brand green, no legend, no zoom, two y labels,
 * a few time labels), sized for a popover. */
function Sparkline({
  points,
  timezone,
  spec,
}: {
  points: [number, number | null][];
  timezone: string;
  spec: TrendSpec;
}) {
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
    // the axis in the spec's steps around the data, so the labels never crowd; a spec
    // without a step takes a round one from the data
    const step =
      spec.step ?? niceStep(Math.min(...values), Math.max(...values));
    const decimals = spec.decimals ?? decimalsFor(step);
    const low =
      spec.floor !== undefined
        ? spec.floor
        : Math.floor((Math.min(...values) - step / 5) / step) * step;
    let high = Math.max(
      low + step,
      Math.ceil((Math.max(...values) + step / 5) / step) * step,
    );
    // two or three even ticks: the axis grows to a multiple of the interval, so the labels
    // sit at equal distances instead of a stray one under the top (Tim, 2026-09-16)
    const steps = Math.max(1, Math.round((high - low) / step));
    const parts =
      steps <= 3 ? steps : ([3, 2].find((n) => steps % n === 0) ?? 3);
    let interval = Math.ceil(steps / parts) * step;
    high = low + interval * parts;
    if (spec.ceiling !== undefined) {
      // a fixed top: a door is 0 or 1, and an axis that runs to 2 says nothing
      high = spec.ceiling;
      interval = step;
    }
    const label = (v: number): string =>
      spec.words?.[Math.round(v)] !== undefined && Number.isInteger(v)
        ? spec.words[Math.round(v)]
        : `${v.toFixed(decimals)}${spec.unit ? ` ${spec.unit}` : ""}`;
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
            return `${formatInZone(new Date(p.value[0]).toISOString(), timezone)}<br/>${p.value[1] == null ? "" : label(p.value[1])}`;
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
          min: Number(low.toFixed(3)),
          max: Number(high.toFixed(3)),
          interval: Number(interval.toFixed(6)),
          axisLabel: {
            color: th.text,
            fontSize: 10,
            formatter: (v: number) =>
              spec.words ? label(v) : v.toFixed(decimals),
          },
          splitLine: { lineStyle: { color: th.grid } },
        },
        series: [
          {
            type: "line",
            data: points,
            step: spec.stepped ? "end" : undefined,
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
  }, [points, timezone, dark, spec]);
  return (
    <div
      ref={container}
      className="h-28 w-full"
      role="img"
      aria-label={spec.ariaLabel}
    />
  );
}
