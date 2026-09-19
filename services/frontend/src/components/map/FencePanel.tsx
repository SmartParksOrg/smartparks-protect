import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { FenceStatus } from "@/api/types";
import { MetricTrend } from "@/components/map/BatteryTrend";
import { PanelRow } from "@/components/map/MapObjectPanel";
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
  return (
    <>
      <PanelRow label={t("Fence")}>
        <FenceLevelDot level={s.level} /> {fenceLevelLabel(s.level, t)}
        {s.changed_at && (
          <span
            className="ml-1 text-xs text-muted-foreground"
            title={formatTime(s.changed_at)}
          >
            {t("since {{ago}}", { ago: formatAgo(s.changed_at, now) })}
          </span>
        )}
      </PanelRow>
      <PanelRow label={t("Thresholds")}>
        {t("live at {{ok}}, down under {{down}}", {
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
          <PanelRow label={t("Sections")}>
            <ul className="space-y-0.5">
              {sections.map((section, i) => (
                <li key={i} className="flex items-center gap-2 text-xs">
                  <FenceLevelDot level={section.level} />
                  <span>
                    {formatLength(section.from_m)} –{" "}
                    {formatLength(section.to_m)}
                  </span>
                  <span className="text-muted-foreground">
                    {section.monitor_ids?.map(monitorName).join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          </PanelRow>
          {monitors.map((m) => (
            <PanelRow key={m.entity_id} label={m.name}>
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 text-xs">
                  <FenceLevelDot level={m.level} />
                  <span>{kilovolts(m.voltage_v)}</span>
                  {m.pulses != null && (
                    <span className="text-muted-foreground">
                      {t("{{count}} pulses", { count: m.pulses })}
                    </span>
                  )}
                  {m.failed && (
                    <span className="text-muted-foreground">
                      {t("measurement failed")}
                    </span>
                  )}
                  {m.measured_at && (
                    <span
                      className="text-muted-foreground"
                      title={formatTime(m.measured_at)}
                    >
                      {formatAgo(m.measured_at, now)}
                    </span>
                  )}
                  <Link
                    className="underline"
                    to={`/projects/${projectId}/entities/${m.entity_id}`}
                  >
                    {t("entity")}
                  </Link>
                </div>
                {m.device_id && (
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
                )}
              </div>
            </PanelRow>
          ))}
        </>
      )}
    </>
  );
}
