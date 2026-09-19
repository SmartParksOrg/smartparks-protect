import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MapPin } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EventItem, Feature, FenceStatus } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { MetricTrend } from "@/components/map/BatteryTrend";
import { FenceLevelDot } from "@/components/map/FencePanel";
import { FenceStrip } from "@/components/map/FenceStrip";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { usePermissions } from "@/hooks/useProjects";
import {
  type FenceMonitor,
  type FenceSection,
  fenceLevelLabel,
  fenceSummary,
  kilovolts,
} from "@/lib/fence";
import { formatAgo, formatTime } from "@/lib/format";
import { formatLength } from "@/lib/geodesy";

/**
 * The full view of a fence line (Tim, 2026-09-19): the line as one bar with its monitors
 * named, every section with its level and monitors, every monitor with its reading and its
 * voltage chart, the status history, and the thresholds the line is judged by. The map's
 * panel shows the essentials and points here.
 */
export function FenceLinePage() {
  const { t } = useTranslation();
  const { projectId = "", featureId = "" } = useParams();
  const { can } = usePermissions(projectId);
  const now = useNow();
  const feature = useQuery({
    queryKey: [...queryKeys.features(projectId), featureId],
    queryFn: () =>
      api.get<Feature>(`/api/v1/projects/${projectId}/features/${featureId}`),
  });
  const status = useQuery({
    queryKey: [...queryKeys.features(projectId), featureId, "fence"],
    queryFn: () =>
      api.get<FenceStatus>(
        `/api/v1/projects/${projectId}/features/${featureId}/fence`,
      ),
    refetchInterval: 60_000,
  });
  const history = useQuery({
    queryKey: [...queryKeys.features(projectId), featureId, "fence-events"],
    queryFn: () =>
      api.get<EventItem[]>(
        `/api/v1/projects/${projectId}/features/${featureId}/fence/events`,
        { query: { limit: 100 } },
      ),
    refetchInterval: 60_000,
  });
  const s = status.data;
  const sections = (s?.sections ?? []) as unknown as FenceSection[];
  const monitors = (s?.monitors ?? []) as unknown as FenceMonitor[];
  const name = (id: string) =>
    monitors.find((m) => m.entity_id === id)?.name ?? "?";
  return (
    <>
      <PageHeader
        title={feature.data?.name ?? t("Fence line")}
        description={
          s
            ? `${t("fence")} · ${fenceLevelLabel(s.level, t)}${
                s.changed_at
                  ? ` ${t("since {{ago}}", { ago: formatAgo(s.changed_at, now) })}`
                  : ""
              }`
            : t("fence")
        }
        leading={
          <Button asChild variant="ghost" size="icon" aria-label={t("Back")}>
            <Link to={`/projects/${projectId}/admin/features`}>
              <ArrowLeft className="size-4" />
            </Link>
          </Button>
        }
        actions={
          <Button asChild size="sm" variant="outline">
            <Link to={`/projects/${projectId}/map?feature=${featureId}`}>
              <MapPin className="size-4" /> {t("Show on map")}
            </Link>
          </Button>
        }
      />
      <Page>
        {s && (
          <Card>
            <CardHeader>
              <CardTitle>
                <FenceLevelDot level={s.level} /> {fenceLevelLabel(s.level, t)}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <FenceStrip
                lengthM={s.length_m}
                sections={sections}
                monitors={monitors}
                labels
              />
              <p className="text-sm">{fenceSummary(sections, monitors, t)}</p>
              <p className="text-xs text-muted-foreground">
                {t("{{length}} long", { length: formatLength(s.length_m) })}
                {" · "}
                {t("live at {{ok}}, down under {{down}}", {
                  ok: kilovolts(s.thresholds.ok_v),
                  down: kilovolts(s.thresholds.down_v),
                })}
                {" · "}
                {t("a monitor silent for {{minutes}} min reads unknown", {
                  minutes: Math.round((2 * s.thresholds.interval_s) / 60),
                })}
              </p>
            </CardContent>
          </Card>
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>{t("Sections")}</CardTitle>
            </CardHeader>
            <CardContent>
              {sections.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("Loading…")}</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-muted-foreground">
                      <th className="py-1 font-normal">{t("Stretch")}</th>
                      <th className="font-normal">{t("Reads")}</th>
                      <th className="font-normal">{t("Monitors")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sections.map((section, i) => (
                      <tr key={i} className="border-t">
                        <td className="py-1 tabular-nums">
                          {formatLength(section.from_m)} –{" "}
                          {formatLength(section.to_m)}
                        </td>
                        <td>
                          <FenceLevelDot level={section.level} />{" "}
                          {fenceLevelLabel(section.level, t)}
                        </td>
                        <td className="text-muted-foreground">
                          {section.monitor_ids?.map(name).join(" · ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("History")}</CardTitle>
            </CardHeader>
            <CardContent>
              {history.data && history.data.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  {t("No change of status recorded yet.")}
                </p>
              )}
              <ul className="space-y-1 text-sm">
                {(history.data ?? []).map((e) => (
                  <li key={e.id} className="flex items-start gap-2">
                    <FenceLevelDot
                      level={String(
                        (e.context as { section_level?: string })
                          .section_level ??
                          (e.context as { level?: string }).level,
                      )}
                    />
                    <span className="min-w-0 flex-1">{e.title}</span>
                    <span
                      className="shrink-0 text-xs text-muted-foreground"
                      title={formatTime(e.time)}
                    >
                      {formatAgo(e.time, now)}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {monitors.map((m) => (
            <Card key={m.entity_id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FenceLevelDot level={m.level} />
                  <Link
                    className="hover:underline"
                    to={`/projects/${projectId}/entities/${m.entity_id}`}
                  >
                    {m.name}
                  </Link>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  {kilovolts(m.voltage_v)}
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
                    <span
                      className="text-muted-foreground"
                      title={formatTime(m.measured_at)}
                    >
                      {" "}
                      · {formatAgo(m.measured_at, now)}
                    </span>
                  )}
                  {m.position_m != null && (
                    <span className="text-muted-foreground">
                      {" "}
                      ·{" "}
                      {t("at {{at}} along the line", {
                        at: formatLength(m.position_m),
                      })}
                    </span>
                  )}
                </p>
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
                      ariaLabel: t("Fence voltage over the period"),
                    }}
                    until={m.measured_at ?? null}
                  />
                )}
              </CardContent>
            </Card>
          ))}
          {s && monitors.length === 0 && (
            <Card>
              <CardContent className="pt-6 text-sm text-muted-foreground">
                {t(
                  "No fence monitor on this line yet. Attach one on its entity page.",
                )}
              </CardContent>
            </Card>
          )}
        </div>
        {feature.data && can("features:write") && (
          <ThresholdsCard projectId={projectId} feature={feature.data} />
        )}
      </Page>
    </>
  );
}

/** The thresholds the line is judged by, for project admins: the attributes under `fence`. */
function ThresholdsCard({
  projectId,
  feature,
}: {
  projectId: string;
  feature: Feature;
}) {
  const { t } = useTranslation();
  const current = ((feature.attributes as { fence?: Record<string, number> })
    .fence ?? {}) as Record<string, number>;
  const [okKv, setOkKv] = useState(String((current.ok_v ?? 4000) / 1000));
  const [downKv, setDownKv] = useState(String((current.down_v ?? 2000) / 1000));
  const [intervalMin, setIntervalMin] = useState(
    String((current.interval_s ?? 60) / 60),
  );
  const save = useMutationToast({
    mutationFn: () =>
      api.patch<Feature>(
        `/api/v1/projects/${projectId}/features/${feature.id}`,
        {
          body: {
            attributes: {
              ...(feature.attributes as Record<string, unknown>),
              fence: {
                ok_v: Math.round(Number(okKv) * 1000),
                down_v: Math.round(Number(downKv) * 1000),
                interval_s: Math.round(Number(intervalMin) * 60),
              },
            },
          },
        },
      ),
    invalidate: [queryKeys.features(projectId)],
    success: t("Thresholds saved"),
  });
  const valid =
    Number(okKv) > Number(downKv) &&
    Number(downKv) > 0 &&
    Number(intervalMin) > 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Thresholds")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          {t(
            "A monitor reads live at or above the first, low below it, down below the second or when it counts no pulses, and unknown when it has been silent for twice the interval.",
          )}
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="fence-ok">{t("Live at (kV)")}</Label>
            <Input
              id="fence-ok"
              type="number"
              step="0.1"
              min={0}
              className="w-28"
              value={okKv}
              onChange={(e) => setOkKv(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="fence-down">{t("Down under (kV)")}</Label>
            <Input
              id="fence-down"
              type="number"
              step="0.1"
              min={0}
              className="w-28"
              value={downKv}
              onChange={(e) => setDownKv(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="fence-interval">
              {t("Measurement interval (min)")}
            </Label>
            <Input
              id="fence-interval"
              type="number"
              step="1"
              min={1}
              className="w-32"
              value={intervalMin}
              onChange={(e) => setIntervalMin(e.target.value)}
            />
          </div>
          <Button
            type="button"
            size="sm"
            disabled={!valid || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("Save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
