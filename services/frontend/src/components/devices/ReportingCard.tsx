import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceReporting } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";

const SOURCE_LABELS: Record<string, string> = {
  override: "set by a person",
  settings_frame: "the collar's own settings",
  command: "a command the collar acknowledged",
  type_default: "the device type's settings",
  learned: "learned from the fixes",
  unknown: "unknown",
};

/** An interval as words: "5 min", "1.5 h", "2 d". */
function intervalWords(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  if (seconds >= 2 * 86_400) return `${(seconds / 86_400).toFixed(0)} d`;
  if (seconds >= 3600) return `${Number((seconds / 3600).toFixed(1))} h`;
  return `${Math.round(seconds / 60)} min`;
}

/**
 * How often the device is expected to report (decisions D225 to D227): the expectation the
 * analyses use with its source, the interval declared by the settings Protect knows, the
 * interval the last 30 days of fixes show with how regular they are, and a person's override.
 * A stale setting is named as such. The device performance analysis reads the same figures.
 */
export function ReportingCard({
  deviceId,
  canEdit,
}: {
  deviceId: string;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const reporting = useQuery({
    queryKey: queryKeys.deviceReporting(deviceId),
    queryFn: () =>
      api.get<DeviceReporting>(`/api/v1/devices/${deviceId}/reporting`),
  });
  const [minutes, setMinutes] = useState("");
  const save = useMutationToast({
    mutationFn: (seconds: number | null) =>
      api.put<DeviceReporting>(`/api/v1/devices/${deviceId}/reporting`, {
        body: { expected_fix_interval_s: seconds },
      }),
    invalidate: [queryKeys.deviceReporting(deviceId)],
    success: (r) =>
      r.override
        ? t("Expected interval set to {{interval}}", {
            interval: intervalWords(r.expected_fix_s),
          })
        : t("The override is cleared; the settings and the data decide again"),
    onSuccess: () => setMinutes(""),
  });
  const r = reporting.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Reporting")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {!r ? (
          <p className="text-muted-foreground">{t("Loading…")}</p>
        ) : (
          <>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-muted-foreground">
                {t("Expected fix interval")}
              </dt>
              <dd>
                {r.expected_fix_s == null
                  ? t("not known")
                  : t("{{interval}}, {{source}}", {
                      interval: intervalWords(r.expected_fix_s),
                      source: t(
                        SOURCE_LABELS[r.expected_source] ?? r.expected_source,
                      ),
                    })}
              </dd>
              {r.declared_fix_s != null && r.expected_source === "learned" && (
                <>
                  <dt className="text-muted-foreground">{t("Settings say")}</dt>
                  <dd className="text-amber-700 dark:text-amber-400">
                    {t(
                      "{{interval}} ({{source}}): stale, the collar does otherwise",
                      {
                        interval: intervalWords(r.declared_fix_s),
                        source: t(
                          SOURCE_LABELS[r.declared_source ?? "unknown"] ??
                            r.declared_source ??
                            "",
                        ),
                      },
                    )}
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">
                {t("Last {{days}} days show", { days: r.learned_days })}
              </dt>
              <dd>
                {r.learned
                  ? t(
                      "every {{interval}}, {{share}}% regular, from {{fixes}} fixes",
                      {
                        interval: intervalWords(r.learned.seconds),
                        share: Math.round(r.learned.regular_share * 100),
                        fixes: r.learned_from_fixes,
                      },
                    )
                  : t("too few fixes to learn from ({{fixes}})", {
                      fixes: r.learned_from_fixes,
                    })}
                {r.learned && !r.learned.confident && (
                  <span className="ml-1 text-muted-foreground">
                    {t("(not regular enough to count missed fixes)")}
                  </span>
                )}
              </dd>
              {r.expected_status_s != null && (
                <>
                  <dt className="text-muted-foreground">
                    {t("Status interval")}
                  </dt>
                  <dd>
                    {t("{{interval}}, {{source}}", {
                      interval: intervalWords(r.expected_status_s),
                      source: t(
                        SOURCE_LABELS[r.status_source ?? "unknown"] ??
                          r.status_source ??
                          "",
                      ),
                    })}
                  </dd>
                </>
              )}
            </dl>
            {canEdit && (
              <div className="flex flex-wrap items-center gap-2 pt-1">
                {r.learned?.confident &&
                  r.expected_source !== "learned" &&
                  r.expected_source !== "override" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={save.isPending}
                      onClick={() =>
                        save.mutate(Math.round(r.learned!.seconds))
                      }
                    >
                      {t("Use the learned interval")}
                    </Button>
                  )}
                <label className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={1}
                    step={1}
                    className="h-8 w-24"
                    placeholder={t("minutes")}
                    aria-label={t("Expected fix interval in minutes")}
                    value={minutes}
                    onChange={(e) => setMinutes(e.target.value)}
                  />
                  <Button
                    size="sm"
                    disabled={
                      save.isPending || !minutes || Number(minutes) <= 0
                    }
                    onClick={() =>
                      save.mutate(Math.round(Number(minutes) * 60))
                    }
                  >
                    {t("Set")}
                  </Button>
                </label>
                {r.override && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={save.isPending}
                    onClick={() => save.mutate(null)}
                  >
                    {t("Clear the override")}
                  </Button>
                )}
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              {t(
                "Missed fixes in the device performance analysis are counted against this interval; a setting the collar plainly does not keep gives way to what the fixes show.",
              )}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
