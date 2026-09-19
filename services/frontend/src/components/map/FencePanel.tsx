import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { FenceStatus } from "@/api/types";
import { FenceStrip } from "@/components/map/FenceStrip";
import { PanelRow } from "@/components/map/MapObjectPanel";
import { useNow } from "@/hooks/useNow";
import {
  type FenceMonitor,
  type FenceSection,
  fenceColor,
  fenceLevelLabel,
  fenceSummary,
} from "@/lib/fence";
import { formatAgo, formatTime } from "@/lib/format";

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
  const newest = monitors
    .map((m) => m.measured_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .pop();
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
      {/* the essentials and nothing more (Tim, 2026-09-19): the line as one bar, one sentence
          naming what is wrong and where, and the way to the page that has the rest */}
      <div className="col-span-2 space-y-1">
        <FenceStrip
          lengthM={s.length_m}
          sections={sections}
          monitors={monitors}
        />
        <p className="text-xs text-muted-foreground">
          {fenceSummary(sections, monitors, t)}
          {monitors.length > 0 && newest && (
            <>
              {" · "}
              {t("{{count}} monitors", { count: monitors.length })}
              {", "}
              {t("newest reading {{ago}}", { ago: formatAgo(newest, now) })}
            </>
          )}
        </p>
      </div>
      <PanelRow label={t("Details")}>
        <Link
          className="underline"
          to={`/projects/${projectId}/features/${featureId}/fence`}
        >
          {t("sections, monitors and history")}
        </Link>
      </PanelRow>
    </>
  );
}
