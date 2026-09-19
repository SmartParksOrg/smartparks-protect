import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { FenceStatus } from "@/api/types";
import { MetricTrend } from "@/components/map/BatteryTrend";
import { PanelRow } from "@/components/map/MapObjectPanel";
import { useIsPhone } from "@/hooks/useMediaQuery";
import { useNow } from "@/hooks/useNow";
import {
  type FenceMonitor,
  type FenceSection,
  fenceColor,
  fenceLevelLabel,
  kilovolts,
} from "@/lib/fence";
import { formatAgo, formatTime } from "@/lib/format";
import { formatLength } from "@/lib/geodesy";

export function FenceLevelDot({ level }: { level: string | null | undefined }) {
  return (
    <span
      className="inline-block size-2.5 shrink-0 rounded-full align-middle"
      style={{ backgroundColor: fenceColor(level) }}
      aria-hidden
    />
  );
}

/**
 * What a fence line reads (phase 32, decisions D264 and D265): its level and since when, the
 * sections along it with theirs, and each monitor's newest voltage, pulses and time, with a
 * voltage chart per monitor the way the battery has one.
 */
export function FenceRows({
  projectId,
  featureId,
}: {
  projectId: string;
  featureId: string;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const phone = useIsPhone();
  const [open, setOpen] = useState<string | null>(null);
  const status = useQuery({
    queryKey: [...queryKeys.features(projectId), featureId, "fence"],
    queryFn: () =>
      api.get<FenceStatus>(
        `/api/v1/projects/${projectId}/features/${featureId}/fence`,
      ),
    refetchInterval: 60_000,
  });
  const s = status.data;
  if (!s) {
    return (
      <PanelRow label={t("Fence")}>
        {status.isError ? t("Could not read the fence.") : t("Loading…")}
      </PanelRow>
    );
  }
  const sections = s.sections as unknown as FenceSection[];
  const monitors = s.monitors as unknown as FenceMonitor[];
  const monitorName = (id: string) =>
    monitors.find((m) => m.entity_id === id)?.name ?? "?";
  const toggle = (id: string) => setOpen((o) => (o === id ? null : id));
  return (
    <>
      <PanelRow label={t("Fence")}>
        <span className="whitespace-nowrap">
          <FenceLevelDot level={s.level} /> {fenceLevelLabel(s.level, t)}
        </span>
        {s.changed_at && (
          <span
            className="ml-1 text-xs text-muted-foreground"
            title={formatTime(s.changed_at)}
          >
            {t("since {{ago}}", { ago: formatAgo(s.changed_at, now) })}
          </span>
        )}
      </PanelRow>
      <PanelRow
        label={t("Thresholds")}
        title={t("live at {{ok}}, down under {{down}}", {
          ok: kilovolts(s.thresholds.ok_v),
          down: kilovolts(s.thresholds.down_v),
        })}
      >
        {phone
          ? `${kilovolts(s.thresholds.ok_v)} / ${kilovolts(s.thresholds.down_v)}`
          : t("live at {{ok}}, down under {{down}}", {
              ok: kilovolts(s.thresholds.ok_v),
              down: kilovolts(s.thresholds.down_v),
            })}
      </PanelRow>
      {monitors.length === 0 ? (
        <PanelRow label={t("Monitors")}>
          <span className="text-muted-foreground">
            {t(
              "No fence monitor on this line yet. Attach one on its entity page.",
            )}
          </span>
        </PanelRow>
      ) : (
        <>
          {/* the sections as their own block across both columns: a range and the monitors
              at its ends read as one line each, where the narrow value column wrapped every
              word (Tim, 2026-09-19) */}
          <div className="col-span-2 space-y-1 text-xs">
            <div className="text-muted-foreground">{t("Sections")}</div>
            {sections.map((section, i) => (
              <div key={i} className="flex items-center gap-2">
                <FenceLevelDot level={section.level} />
                <span className="shrink-0 tabular-nums">
                  {formatLength(section.from_m)} – {formatLength(section.to_m)}
                </span>
                <span className="min-w-0 truncate text-muted-foreground">
                  {section.monitor_ids?.map(monitorName).join(" · ")}
                </span>
              </div>
            ))}
          </div>
          {/* one line per monitor: its name, then what it reads, wrapping to a second line on
              a phone and never into the narrow value column */}
          <div className="col-span-2 space-y-1 text-sm">
            {monitors.map((m) => (
              <Fragment key={m.entity_id}>
                <div
                  className="flex flex-wrap items-center gap-x-2"
                  title={m.measured_at ? formatTime(m.measured_at) : undefined}
                >
                  <FenceLevelDot level={m.level} />
                  <Link
                    className="min-w-0 flex-1 truncate font-medium hover:underline"
                    to={`/projects/${projectId}/entities/${m.entity_id}`}
                  >
                    {m.name}
                  </Link>
                  <span className="whitespace-nowrap">
                    {m.device_id ? (
                      <button
                        type="button"
                        className="underline underline-offset-2 hover:text-primary"
                        title={
                          open === m.entity_id
                            ? t("Hide the fence voltage")
                            : t("Show the fence voltage")
                        }
                        aria-expanded={open === m.entity_id}
                        onClick={() => toggle(m.entity_id)}
                      >
                        {kilovolts(m.voltage_v)}
                      </button>
                    ) : (
                      kilovolts(m.voltage_v)
                    )}
                    {m.pulses != null && (
                      <span className="text-muted-foreground">
                        {" "}
                        · {t("{{count}} pulses", { count: m.pulses })}
                      </span>
                    )}
                    {m.failed && (
                      <span className="text-muted-foreground">
                        {" "}
                        · {t("measurement failed")}
                      </span>
                    )}
                    {m.measured_at && (
                      <span className="text-muted-foreground">
                        {" "}
                        · {formatAgo(m.measured_at, now)}
                      </span>
                    )}
                  </span>
                </div>
                {open === m.entity_id && m.device_id && (
                  <div className="rounded-md border bg-muted/30 p-2">
                    <MetricTrend
                      projectId={projectId}
                      deviceId={m.device_id}
                      spec={{
                        metric: "fence_voltage",
                        label: t("Fence voltage"),
                        unit: "kV",
                        scale: 0.001,
                        decimals: 2,
                        floor: 0,
                        ariaLabel: t("Fence voltage"),
                      }}
                      until={m.measured_at ?? null}
                    />
                  </div>
                )}
              </Fragment>
            ))}
          </div>
        </>
      )}
    </>
  );
}
