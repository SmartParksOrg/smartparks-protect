import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { OffloadStation, OffloadStationSetupResult } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { formatAgo, formatDuration, formatTime } from "@/lib/format";

/**
 * What an offload station's cards brought to Protect (phase 42, decision D322): the files and
 * their frames, the trackers the station served in the last 30 days, and the station's own
 * last report of itself (port 23: the card, the visits, the errors). Shown only once the
 * device has acted as a station, so an ordinary tracker's page carries nothing of it.
 */
export function OffloadStationCard({
  deviceId,
  projectId,
  canEdit = false,
}: {
  deviceId: string;
  projectId?: string;
  /** Whether the person may make the station static or mobile (devices:write). */
  canEdit?: boolean;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const read = useQuery({
    queryKey: queryKeys.offloadStation(deviceId),
    queryFn: () =>
      api.get<OffloadStation>(`/api/v1/devices/${deviceId}/offload`),
  });
  // static or mobile (decision D336): the Offload page's setup call, with `mobile` alone
  const mobility = useMutationToast({
    mutationFn: (mobile: boolean) =>
      api.post<OffloadStationSetupResult>(
        `/api/v1/projects/${projectId}/offload/stations`,
        {
          body: { device_id: deviceId, mobile },
        },
      ),
    invalidate: [
      queryKeys.offloadStation(deviceId),
      queryKeys.device(deviceId),
      ...(projectId
        ? [
            queryKeys.projectOffload(projectId),
            queryKeys.currentState(projectId),
          ]
        : []),
    ],
    success: (r) =>
      r.mobile
        ? t(
            "{{device}} is a mobile station now; its own fixes say where it is",
            {
              device: r.device_name,
            },
          )
        : t("{{device}} is a static station now; set its place under Place", {
            device: r.device_name,
          }),
  });
  const s = read.data;
  if (!s || !s.is_station) return null;
  const trackers = s.trackers ?? [];
  const state = s.state as
    | {
        status?: Record<string, boolean | null>;
        counters?: Record<string, number>;
        uptime_seconds?: number;
        storage_pending?: number;
        sd_capacity_mb?: number | null;
        sd_free_percent?: number | null;
      }
    | null
    | undefined;
  const yesNo = (value: boolean | null | undefined) =>
    value == null ? t("unknown") : value ? t("yes") : t("no");
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HardDrive className="size-4" /> {t("Offload station")}
          {s.station_eui && (
            <span className="font-mono text-xs font-normal text-muted-foreground">
              {s.station_eui}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="text-muted-foreground">{t("Position")}</dt>
          <dd>
            {s.mobile
              ? t("mobile: it travels and reports its position itself")
              : t("static: a place set by hand")}
            {canEdit && projectId && (
              <Button
                size="sm"
                variant="link"
                className="h-auto px-2 py-0"
                disabled={mobility.isPending}
                onClick={() => mobility.mutate(!s.mobile)}
              >
                {s.mobile ? t("Make it static") : t("Make it mobile")}
              </Button>
            )}
          </dd>
          <dt className="text-muted-foreground">{t("Card files")}</dt>
          <dd>
            {t("{{files}} files, {{frames}} frames", {
              files: s.files,
              frames: s.frames,
            })}
            {s.last_upload_at
              ? t(", last uploaded {{ago}}", {
                  ago: formatAgo(s.last_upload_at, now),
                })
              : ""}
          </dd>
          <dt className="text-muted-foreground">{t("Records")}</dt>
          <dd>
            {t("{{fresh}} new, {{known}} known through another path", {
              fresh: s.records_new,
              known: s.records_known,
            })}
            {s.frames_repeated > 0
              ? t(", {{count}} repeated frames", { count: s.frames_repeated })
              : ""}
            {s.frames_retained > 0
              ? t(", {{count}} frames of unknown trackers", {
                  count: s.frames_retained,
                })
              : ""}
          </dd>
          {s.last_reception_at && (
            <>
              <dt className="text-muted-foreground">{t("Last offload")}</dt>
              <dd title={formatTime(s.last_reception_at)}>
                {formatAgo(s.last_reception_at, now)}
              </dd>
            </>
          )}
        </dl>
        {trackers.length > 0 && (
          <div>
            <div className="mb-1 text-xs text-muted-foreground">
              {t("Trackers served in the last 30 days")}
            </div>
            <ul className="space-y-0.5">
              {trackers.map((tr) => (
                <li
                  key={tr.device_id ?? tr.dev_addr ?? String(tr.frames)}
                  className="flex flex-wrap items-center gap-x-2"
                >
                  {tr.device_id && projectId ? (
                    <Link
                      className="underline"
                      to={`/projects/${projectId}/devices/${tr.device_id}`}
                    >
                      {tr.device_name ??
                        tr.dev_addr ??
                        tr.device_id.slice(0, 8)}
                    </Link>
                  ) : (
                    <span>
                      {tr.device_name ?? tr.dev_addr ?? t("unknown tracker")}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {t("{{count}} frames", { count: tr.frames })}
                    {tr.mean_rssi != null
                      ? ` · ${tr.mean_rssi.toFixed(0)} dBm`
                      : ""}
                    {tr.last_reception_at
                      ? ` · ${formatAgo(tr.last_reception_at, now)}`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {state && (
          <div>
            <div className="mb-1 text-xs text-muted-foreground">
              {s.state_time
                ? t("The station's own report, {{ago}}", {
                    ago: formatAgo(s.state_time, now),
                  })
                : t("The station's own report")}
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-muted-foreground">{t("SD card in")}</dt>
              <dd>{yesNo(state.status?.card_detected)}</dd>
              <dt className="text-muted-foreground">{t("SD card writable")}</dt>
              <dd>{yesNo(state.status?.card_writable)}</dd>
              {state.status?.sd_card_missing != null && (
                <>
                  <dt className="text-muted-foreground">{t("SD card missing")}</dt>
                  <dd>{yesNo(state.status.sd_card_missing)}</dd>
                </>
              )}
              {state.status?.sdfs_error != null && (
                <>
                  <dt className="text-muted-foreground">{t("Storage fault")}</dt>
                  <dd>{yesNo(state.status.sdfs_error)}</dd>
                </>
              )}
              {state.sd_capacity_mb != null && state.sd_free_percent != null && (
                <>
                  <dt className="text-muted-foreground">{t("SD card space")}</dt>
                  <dd>
                    {t("{{free}}% free of {{size}} MB", {
                      free: state.sd_free_percent,
                      size: state.sd_capacity_mb,
                    })}
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">{t("Listening")}</dt>
              <dd>{yesNo(state.status?.lp0_listening)}</dd>
              {state.uptime_seconds != null && (
                <>
                  <dt className="text-muted-foreground">{t("Uptime")}</dt>
                  <dd>{formatDuration(state.uptime_seconds)}</dd>
                </>
              )}
              {state.counters && (
                <>
                  <dt className="text-muted-foreground">{t("Visits")}</dt>
                  <dd>
                    {t("{{complete}} complete, {{partial}} partial", {
                      complete: state.counters.visits_complete ?? 0,
                      partial: state.counters.visits_partial ?? 0,
                    })}
                  </dd>
                  <dt className="text-muted-foreground">{t("Frames saved")}</dt>
                  <dd>
                    {t("{{saved}} of {{received}} received", {
                      saved: state.counters.data_saved ?? 0,
                      received: state.counters.data_received ?? 0,
                    })}
                  </dd>
                  <dt className="text-muted-foreground">{t("Card errors")}</dt>
                  <dd>
                    {(state.counters.sd_media_errors ?? 0) +
                      (state.counters.sdfs_errors ?? 0)}
                  </dd>
                </>
              )}
            </dl>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
