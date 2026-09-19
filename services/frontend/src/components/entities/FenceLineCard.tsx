import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityFence, Feature, Page as PageType } from "@/api/types";
import { FenceLevelDot } from "@/components/map/FencePanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useNow } from "@/hooks/useNow";
import { type FenceMonitor, fenceLevelLabel, kilovolts } from "@/lib/fence";
import { formatAgo, formatTime } from "@/lib/format";

/**
 * Which fence line a Fence monitor stands on (phase 32, decision D263), and what it last
 * read. A monitor on no line still measures; it just colours nothing on the map.
 */
export function FenceLineCard({
  projectId,
  entityId,
  canEdit,
}: {
  projectId: string;
  entityId: string;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const mine = useQuery({
    queryKey: [...queryKeys.entity(projectId, entityId), "fence"],
    queryFn: () =>
      api.get<EntityFence>(
        `/api/v1/projects/${projectId}/entities/${entityId}/fence`,
      ),
  });
  const lines = useQuery({
    queryKey: [...queryKeys.features(projectId), "fence-lines"],
    queryFn: () =>
      api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, {
        query: { feature_type: "fence", limit: 200 },
      }),
  });
  const m = mine.data;
  const reading = (m?.monitor ?? null) as FenceMonitor | null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Fence line")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          {t(
            "The stretch of fence this monitor watches. The line reads its status from the monitors on it, section by section.",
          )}
        </p>
        <p>
          {m?.feature_id
            ? null
            : canEdit
              ? t(
                  "Not on a fence line. Open the line's page and drag this monitor onto it.",
                )
              : t("No fence line")}
        </p>
        {m?.feature_id && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted-foreground">{t("Line")}</dt>
            <dd>
              <FenceLevelDot level={m.level} /> {fenceLevelLabel(m.level, t)}{" "}
              <Link
                className="underline"
                to={`/projects/${projectId}/features/${m.feature_id}/fence`}
              >
                {m.feature_name}
              </Link>
            </dd>
            <dt className="text-muted-foreground">{t("This monitor")}</dt>
            <dd>
              {reading ? (
                <>
                  <FenceLevelDot level={reading.level} />{" "}
                  {kilovolts(reading.voltage_v)}
                  {reading.pulses != null && (
                    <span className="ml-1 text-muted-foreground">
                      {t("{{count}} pulses", { count: reading.pulses })}
                    </span>
                  )}
                  {reading.measured_at && (
                    <span
                      className="ml-1 text-muted-foreground"
                      title={formatTime(reading.measured_at)}
                    >
                      {formatAgo(reading.measured_at, now)}
                    </span>
                  )}
                </>
              ) : (
                t("Nothing measured yet")
              )}
            </dd>
          </dl>
        )}
        {lines.data && lines.data.items.length === 0 && (
          <p className="text-xs text-muted-foreground">
            {t(
              "No fence line drawn yet. Draw one on the map or the Features page.",
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
