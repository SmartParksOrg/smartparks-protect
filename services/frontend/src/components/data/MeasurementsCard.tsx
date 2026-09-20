import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import type { MetricSummary } from "@/api/types";
import { MetricTrend } from "@/components/map/BatteryTrend";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMetricsByKey } from "@/hooks/useMetrics";
import { useNow } from "@/hooks/useNow";
import { formatAgo, formatTime } from "@/lib/format";
import { trendSpecFor } from "@/lib/trend";

const DAYS = 30;

/**
 * Every metric a device or an entity reported in the last thirty days (Tim, 2026-09-20): the
 * newest reading, when, and how many; a numeric one unfolds its trend. The processed side of
 * the Data tab, beside the positions and the events, which were there and this was not.
 */
export function MeasurementsCard({
  projectId,
  deviceId,
  entityId,
  trendDeviceId,
  recordsTo,
  className,
}: {
  projectId: string;
  deviceId?: string;
  entityId?: string;
  /** The device whose series a trend reads: the device itself, or the entity's device today. */
  trendDeviceId?: string | null;
  recordsTo?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const metrics = useMetricsByKey();
  const [open, setOpen] = useState<string | null>(null);
  const summary = useQuery({
    queryKey: [
      "projects",
      projectId,
      "measurements-summary",
      deviceId ?? "",
      entityId ?? "",
    ],
    queryFn: () =>
      api.get<MetricSummary[]>(
        `/api/v1/projects/${projectId}/measurements/summary`,
        {
          query: { device_id: deviceId, entity_id: entityId, days: DAYS },
        },
      ),
    enabled: Boolean(deviceId || entityId),
    refetchInterval: 60_000,
  });
  const show = (m: MetricSummary): string => {
    if (m.value === null || m.value === undefined) return "–";
    if (typeof m.value === "boolean") return m.value ? t("yes") : t("no");
    if (typeof m.value === "number") {
      const text =
        Math.abs(m.value) >= 100
          ? m.value.toFixed(0)
          : Number.isInteger(m.value)
            ? String(m.value)
            : m.value.toFixed(2);
      return m.unit ? `${text} ${m.unit}` : text;
    }
    return String(m.value);
  };
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("Metrics")}</CardTitle>
        {recordsTo && (
          <Button asChild variant="link" size="sm" className="h-auto p-0">
            <Link to={recordsTo}>{t("All records")}</Link>
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <div className="mb-2 text-xs text-muted-foreground">
          {t(
            "Every metric reported in the last {{days}} days: the newest reading and how many there were.",
            {
              days: DAYS,
            },
          )}
        </div>
        {summary.data && summary.data.length === 0 && (
          <div className="text-sm text-muted-foreground">
            {t("No measurements in those {{days}} days.", { days: DAYS })}
          </div>
        )}
        {summary.data && summary.data.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1 font-normal">{t("Metric")}</th>
                <th className="font-normal">{t("Newest")}</th>
                <th className="hidden font-normal sm:table-cell">
                  {t("When")}
                </th>
                <th className="text-right font-normal">{t("Readings")}</th>
              </tr>
            </thead>
            <tbody>
              {summary.data.map((m) => {
                const spec =
                  m.value_type === "numeric" && trendDeviceId
                    ? trendSpecFor(m.metric_key, metrics.get(m.metric_key), t)
                    : null;
                const unfolded = open === m.metric_key;
                return (
                  <FragmentRow key={m.metric_key}>
                    <tr className="border-t">
                      <td className="py-1">
                        {spec ? (
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
                            aria-expanded={unfolded}
                            title={
                              unfolded
                                ? t("Hide the trend")
                                : t("Show the trend of {{metric}}", {
                                    metric: m.label,
                                  })
                            }
                            onClick={() =>
                              setOpen(unfolded ? null : m.metric_key)
                            }
                          >
                            {unfolded ? (
                              <ChevronDown className="size-3.5" />
                            ) : (
                              <ChevronRight className="size-3.5" />
                            )}
                            {m.label}
                          </button>
                        ) : (
                          m.label
                        )}
                      </td>
                      <td className="tabular-nums">{show(m)}</td>
                      <td
                        className="hidden text-muted-foreground sm:table-cell"
                        title={formatTime(m.time)}
                      >
                        {formatAgo(m.time, now)}
                      </td>
                      <td className="text-right tabular-nums">{m.count}</td>
                    </tr>
                    {unfolded && spec && trendDeviceId && (
                      <tr>
                        <td colSpan={4} className="pb-2">
                          <div className="rounded-md border bg-muted/30 p-2">
                            <MetricTrend
                              projectId={projectId}
                              deviceId={trendDeviceId}
                              spec={spec}
                              until={m.time}
                            />
                          </div>
                        </td>
                      </tr>
                    )}
                  </FragmentRow>
                );
              })}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

/** Two table rows under one key. */
function FragmentRow({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
